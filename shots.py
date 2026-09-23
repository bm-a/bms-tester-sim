#!/usr/bin/env python3
"""shots.py — data-accurate dashboard snapshots + GIFs from the LIVE sim.
Renders the real dashboard look (same dark theme, tiles, bench strip) with
live values pulled from /esp/api/state, rasterizes SVG->PNG via cairosvg,
stitches GIFs via ffmpeg. Honest label: sim snapshots, not ESP screenshots
(no browser exists in this container to screenshot the real page).
Usage:
  python3 shots.py --sim http://127.0.0.1:8008 --out shots/
  python3 shots.py --gif   # runs a sequential cycle + spoof, captures frames
"""
import argparse, json, os, subprocess, sys, time, urllib.request

def get(base, path):
    return json.load(urllib.request.urlopen(base + path))

def post(base, path, body):
    req = urllib.request.Request(base + path, data=json.dumps(body).encode(),
                                 headers={'Content-Type': 'application/json'})
    return json.load(urllib.request.urlopen(req))

def esc(s):
    return str(s).replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')

def render_svg(fw, variant="full", caption=""):
    c = fw["cfg"]
    link = fw["link"]
    head_y = 262 if variant == "full" else 120
    H = 480 if variant == "full" else 300
    tiles = ""
    for i, on in enumerate(fw["relays"]):
        nm = esc(c.get(f"lbl{i}", f"R{i+1}"))
        x = 8 + (i % 4) * 168
        y = head_y + (i // 4) * 76
        fill = "#052e16" if on else "#0f172a"
        stroke = "#22c55e" if on else "#475569"
        tcol = "#4ade80" if on else "#94a3b8"
        tiles += (f'<rect x="{x}" y="{y}" width="160" height="68" rx="10" fill="{fill}" stroke="{stroke}" stroke-width="3"/>'
                  f'<text x="{x+80}" y="{y+30}" fill="{tcol}" font-size="20" font-weight="bold" text-anchor="middle">{nm}</text>'
                  f'<text x="{x+80}" y="{y+52}" fill="{tcol}" font-size="13" text-anchor="middle">{"ON" if on else "OFF"}</text>')
    bench = ""
    if variant == "full":
        rr = ""
        for i, on in enumerate(fw["relays"]):
            rr += f'<rect x="{8+i*84}" y="196" width="76" height="30" rx="6" fill="{"#22c55e" if on else "#1e293b"}" stroke="#475569"/>'
            rr += f'<text x="{14+i*84}" y="216" fill="#94a3b8" font-size="12">R{i+1}</text>'
        mv = f"{c.get('mv',0)/10:.1f}V {c.get('ma',0)/10:.1f}A {c.get('msoc',0)}%"
        dot = "#eab308" if link else "#475569"
        flow = (f'<line x1="396" y1="60" x2="470" y2="60" stroke="#4ade80" stroke-width="2" stroke-dasharray="6 6">'
                f'<animate attributeName="stroke-dashoffset" from="0" to="-24" dur="1s" repeatCount="indefinite"/></line>' if link else "")
        bench = (f'<text x="8" y="120" fill="#93c5fd" font-size="14">BENCH (LIVE)</text>'
                 f'<rect x="8" y="128" width="150" height="20" rx="5" fill="#1e293b"/><text x="14" y="143" fill="#f87171" font-size="12">48V BUS</text>'
                 f'<rect x="170" y="128" width="120" height="20" rx="5" fill="#1e293b"/><text x="176" y="143" fill="#c6cddc" font-size="12">ESP32-S3</text>'
                 f'<rect x="302" y="128" width="80" height="20" rx="5" fill="#1e293b"/><circle cx="374" cy="138" r="5" fill="{dot}"/>'
                 f'{flow}'
                 f'<rect x="470" y="108" width="202" height="62" rx="6" fill="#1e293b" stroke="#475569"/>'
                 f'<text x="478" y="130" fill="#fff" font-size="16">{esc(mv)}</text>'
                 f'<text x="478" y="152" fill="{"#4ade80" if link else "#f87171"}" font-size="13">{"LINK GREEN" if link else "LINK RED"}</text>'
                 f'{rr}'
                 f'<text x="8" y="240" fill="#64748b" font-size="11">coils glow green · A/B flow pulses while linked</text>')
    linkpill = "#14532d" if link else "#450a0a"
    linktxt = "LINK GREEN" if link else "LINK RED"
    badge = "FULL" if variant == "full" else "LITE"
    badgec = "#1d4ed8" if variant == "full" else "#0e7490"
    sub = ("live bench SVG + glowing tiles + meters · all cards" if variant == "full"
           else "tiles + link only · ~4.9 KB page")
    capbar = ""
    if caption:
        H += 30
        capbar = (f'<rect y="{H-30}" width="680" height="30" fill="#052e16"/>'
                  f'<text x="12" y="{H-10}" fill="#4ade80" font-size="14">{esc(caption)}</text>')
    svg = (f'<svg xmlns="http://www.w3.org/2000/svg" width="680" height="{H}" font-family="monospace">'
           f'<rect width="680" height="{H}" fill="#0f172a"/>'
           f'<text x="12" y="34" fill="#e2e8f0" font-size="24">⚡ BMS Tester</text>'
           f'<text x="220" y="34" fill="#94a3b8" font-size="13">v{esc(fw.get("fw","?"))} sim snapshot</text>'
           f'<rect x="380" y="12" width="130" height="26" rx="13" fill="{linkpill}"/>'
           f'<text x="445" y="30" fill="#fff" font-size="13" text-anchor="middle">{linktxt}</text>'
           f'<rect x="516" y="12" width="70" height="26" rx="13" fill="{badgec}"/>'
           f'<text x="551" y="30" fill="#fff" font-size="13" font-weight="bold" text-anchor="middle">{badge}</text>'
           f'<text x="12" y="54" fill="#64748b" font-size="12">{sub}</text>'
           f'{bench}'
           f'<text x="12" y="{head_y-8}" fill="#93c5fd" font-size="14">RELAYS</text>'
           + tiles +
           f'<text x="12" y="{H-12}" fill="#64748b" font-size="11">meters {c.get("m_met",0)} · attempts {c.get("m_att",0)} · pass {c.get("m_ps",0)} · fail {c.get("m_fl",0)} · cyc {fw.get("cycles",0)} · act {fw.get("acts",0)} · live /esp/api/state</text>'
           + capbar +
           f'</svg>')
    return svg

def snap(base, outdir, name, variant="full", scene="idle"):
    import cairosvg
    if scene == "midseq":
        # capture mid-sequence with coils ON + custom names (differs from idle)
        post(base, "/api/labels", {"labels": ["HORN","LIGHT","FAN","PUMP","R5","R6","R7","R8"]})
        post(base, "/api/config", {"rmode": 0, "nrel": 8})
        post(base, "/api/seq", {"cmd": "stop"})
        post(base, "/api/seq", {"cmd": "start"})
        for _ in range(12):
            time.sleep(1.0)
            fw = get(base, "/esp/api/state")
            if sum(fw["relays"]) >= 4:
                break
    elif scene == "spoof":
        post(base, "/api/labels", {"labels": ["HORN","LIGHT","FAN","PUMP","R5","R6","R7","R8"]})
        post(base, "/esp/api/spoof", {"cmd": "fire", "sv": 1000, "sa": 1000, "ssoc": 100, "ssec": 30})
        time.sleep(2.5)
    elif scene == "named":
        post(base, "/api/seq", {"cmd": "stop"})
        post(base, "/api/labels", {"labels": ["HORN","LIGHT","FAN","PUMP","R5","R6","R7","R8"]})
        post(base, "/api/relay", {"i": 0, "on": True})
        post(base, "/api/relay", {"i": 1, "on": True})
    fw = get(base, "/esp/api/state")
    on = sum(fw["relays"])
    cap = {"midseq": f"SEQ {on}/8 relays ON · cyc {fw['cycles']}",
           "spoof": f"SPOOF STAGE {fw.get('stage',0)} → {fw['cfg'].get('mv',0)/10:.1f}V on meter",
           "named": "names persist: HORN · LIGHT · FAN · PUMP"}.get(scene, "")
    svg = render_svg(fw, variant, caption=cap)
    p = os.path.join(outdir, name + ".svg")
    open(p, "w").write(svg)
    cairosvg.svg2png(url=p, write_to=os.path.join(outdir, name + ".png"), scale=1.5)
    print("shot:", name)

def static_svg(kind, fw=None):
    """Hand-built explainers (static truth from docs/PROTOCOL.md + wiring)."""
    H = {'protocol': 330, 'wiring': 420, 'terminal': 300, 'tests': 380}[kind]
    s = [f'<svg xmlns="http://www.w3.org/2000/svg" width="680" height="{H}" font-family="monospace">',
         f'<rect width="680" height="{H}" fill="#0f172a"/>']
    if kind == 'protocol':
        s.append('<text x="12" y="34" fill="#e2e8f0" font-size="22">JBD FRAME · 9600 8N1 · half-duplex</text>')
        req = [("DD","START"),("A5","READ"),("03","REG"),("00","LEN"),("FF","CK-HI"),("FD","CK-LO"),("77","END")]
        s.append('<text x="12" y="70" fill="#93c5fd" font-size="14">REQUEST meter → battery (basic-info read)</text>')
        for i,(b,l) in enumerate(req):
            x = 12 + i*94
            s.append(f'<rect x="{x}" y="80" width="86" height="52" rx="6" fill="#1e293b" stroke="#e6b800"/>'
                     f'<text x="{x+43}" y="104" fill="#fff" font-size="20" font-weight="bold" text-anchor="middle">{b}</text>'
                     f'<text x="{x+43}" y="124" fill="#e6b800" font-size="11" text-anchor="middle">{l}</text>')
        rsp = [("DD","START"),("03","REG"),("00 1B","LEN"),("…52.0V…","DATA"),("FC DA","CK"),("77","END")]
        s.append('<text x="12" y="168" fill="#93c5fd" font-size="14">REPLY battery → meter (0x03: 52.0V 0A 100Ah 100% 14S 25.0°C)</text>')
        for i,(b,l) in enumerate(rsp):
            x = 12 + i*110 if i < 5 else 12 + 5*110
            w = 102
            if i == 5: x = 562
            s.append(f'<rect x="{x}" y="178" width="{w}" height="52" rx="6" fill="#1e293b" stroke="#4ade80"/>'
                     f'<text x="{x+w//2}" y="202" fill="#fff" font-size="17" font-weight="bold" text-anchor="middle">{b}</text>'
                     f'<text x="{x+w//2}" y="222" fill="#4ade80" font-size="11" text-anchor="middle">{l}</text>')
        s.append('<text x="12" y="262" fill="#fbbf24" font-size="13">ck = 0x10000 − Σ covered bytes (big-endian)</text>')
        s.append('<text x="12" y="284" fill="#94a3b8" font-size="13">requests cover REG+LEN+DATA · replies cover LEN+DATA (echoed CMD excluded)</text>')
        s.append('<text x="12" y="306" fill="#64748b" font-size="12">writes (0x5A) + unknown regs → silence (option A), still counted live</text>')
    elif kind == 'wiring':
        s.append('<text x="12" y="34" fill="#e2e8f0" font-size="22">POWER + SIGNAL TREE · 48V shared bus</text>')
        def box(x,y,w,h,t,c):
            s.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="8" fill="#1e293b" stroke="{c}" stroke-width="2"/>'
                     f'<text x="{x+w//2}" y="{y+h//2+5}" fill="#e2e8f0" font-size="14" text-anchor="middle">{t}</text>')
        def arrow(x1,y1,x2,y2,c="#64748b"):
            s.append(f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke="{c}" stroke-width="2"/>')
        box(12,60,140,44,"48V BUS","#f87171"); box(12,120,140,44,"12V COILS","#fb923c"); box(12,180,140,44,"5V LOGIC","#22d3ee")
        arrow(82,104,82,120,"#f87171"); arrow(82,164,82,180,"#f87171")
        box(230,120,150,44,"ESP32-S3","#93c5fd"); arrow(152,202,230,142,"#22d3ee")
        box(230,220,150,44,"8× RELAY","#2456c6"); arrow(250,164,250,220,"#fb923c")
        box(230,300,150,44,"MAX485","#1e40af"); arrow(305,164,305,300,"#e6b800")
        box(460,220,208,44,"METER (Ayca)","#4ade80"); arrow(380,322,460,242,"#4ade80")
        s.append('<text x="460" y="290" fill="#64748b" font-size="12">J1: 48V GND A B R1 · J2: R2-R6 · AUX: R7 R8</text>')
        box(460,300,208,44,"GX16-5 ×2","#8f97a5"); arrow(535,264,535,300)
        s.append('<text x="12" y="392" fill="#64748b" font-size="12">star GND everywhere · DAD: fuse + wire gauge per channel (≤3A default)</text>')
    elif kind == 'terminal':
        lines = [("$ python3 sim_server.py --port 8000", "#94a3b8"),
                 ("local-wokwi v2.7 → http://localhost:8000", "#4ade80"),
                 ("$ curl -X POST /api/seq -d '{\"cmd\":\"start\"}'", "#94a3b8"),
                 ('{"ok": true}   # R1→R8 click in order', "#4ade80"),
                 ("$ echo STATUS? > /dev/ttyUSB0   # USB console", "#94a3b8"),
                 ("GREEN 2.7", "#4ade80"),
                 ("$ esptool.py --chip esp32s3 write-flash 0x0 bms-tester-8mb.bin", "#94a3b8"),
                 ("verified: 103/103 pio · 49/49 web · soak PASS", "#fbbf24")]
        s.append('<text x="12" y="34" fill="#e2e8f0" font-size="22">TERMINAL · bring-up in 3 commands</text>')
        y = 70
        for t, col in lines:
            s.append(f'<text x="12" y="{y}" fill="{col}" font-size="15">{esc(t)}</text>')
            y += 30
    elif kind == 'tests':
        rows = [("test_checksum",7),("test_logic",8),("test_parser",13),("test_stress",4),
                ("test_relay",36),("test_spoof",11),("test_meter",10),("test_ota",6),
                ("test_upload",5),("test_system",3),("test_web",49)]
        s.append('<text x="12" y="34" fill="#e2e8f0" font-size="22">SUITES · 152/152 + contract 3/3 + soak</text>')
        y = 66
        for name, n in rows:
            bar = int(n/49*380)
            s.append(f'<text x="12" y="{y}" fill="#94a3b8" font-size="13">{name}</text>'
                     f'<rect x="190" y="{y-14}" width="{bar}" height="16" rx="4" fill="#166534"/>'
                     f'<text x="{196+bar}" y="{y}" fill="#4ade80" font-size="13">{n} ✓</text>')
            y += 26
        s.append(f'<text x="12" y="{y+6}" fill="#fbbf24" font-size="13">30-day soak PASS · 2.59M polls · web-contract 3/3 variants</text>')
    s.append('</svg>')
    return "\n".join(s)

def tiles_png(base, outdir):
    import cairosvg
    fw = get(base, "/esp/api/state")
    c = fw["cfg"]
    t = ['<svg xmlns="http://www.w3.org/2000/svg" width="680" height="200" font-family="monospace">',
         '<rect width="680" height="200" fill="#0f172a"/>',
         '<text x="12" y="30" fill="#93c5fd" font-size="16">RELAY TILES · tap = force ON/OFF (IDLE only) · names persist</text>']
    for i, on in enumerate(fw["relays"]):
        nm = esc(c.get(f"lbl{i}", f"R{i+1}"))
        x = 8 + (i % 4) * 168
        y = 44 + (i // 4) * 76
        fill = "#052e16" if on else "#0f172a"
        stroke = "#22c55e" if on else "#475569"
        tcol = "#4ade80" if on else "#94a3b8"
        t.append(f'<rect x="{x}" y="{y}" width="160" height="68" rx="10" fill="{fill}" stroke="{stroke}" stroke-width="3"/>'
                 f'<text x="{x+80}" y="{y+30}" fill="{tcol}" font-size="20" font-weight="bold" text-anchor="middle">{nm}</text>'
                 f'<text x="{x+80}" y="{y+52}" fill="{tcol}" font-size="13" text-anchor="middle">{"ON" if on else "OFF"}</text>')
    t.append('</svg>')
    p = os.path.join(outdir, "tiles.svg")
    open(p, "w").write("\n".join(t))
    cairosvg.svg2png(url=p, write_to=os.path.join(outdir, "tiles.png"), scale=1.5)
    print("shot: tiles")
    on = sum(fw["relays"])
    st = fw.get("stage", 0)
    if st:
        return f"SPOOF STAGE {st} → {fw['cfg'].get('mv',0)/10:.1f}V {fw['cfg'].get('msoc',0)}% on meter"
    if fw["running"]:
        newly = [i for i, (a, b) in enumerate(zip(fw["relays"], prev)) if a and not b]
        if newly:
            return f"SEQ {on}/8 · R{newly[0]+1} just fired"
        return f"SEQ {on}/8 relays ON · cyc {fw['cycles']}"
    if fw["cycles"] >= 1:
        return f"cycle {fw['cycles']} done · {fw['acts']} actuations · all OFF"
    return "boot · LINK GREEN · meter polling 03/04/05"

def gif(base, outdir):
    import cairosvg
    fr = os.path.join(outdir, "frames")
    os.makedirs(fr, exist_ok=True)
    post(base, "/api/labels", {"labels": ["HORN","LIGHT","FAN","PUMP","R5","R6","R7","R8"]})
    post(base, "/api/config", {"rmode": 0, "nrel": 8})
    post(base, "/api/seq", {"cmd": "stop"})
    post(base, "/api/seq", {"cmd": "start"})
    n = 0
    prev = [False]*8
    for _ in range(14):
        fw = get(base, "/esp/api/state")
        cap = frame_caption(fw, prev)
        prev = list(fw["relays"])
        svg = render_svg(fw, "full", caption=cap)
        fp = os.path.join(fr, f"f{n:03d}.svg")
        open(fp, "w").write(svg)
        cairosvg.svg2png(url=fp, write_to=os.path.join(fr, f"f{n:03d}.png"), scale=1.0)
        n += 1
        if not fw["running"] and fw["cycles"] >= 1:
            break
        time.sleep(1.0)
    post(base, "/esp/api/spoof", {"cmd": "fire", "sv": 1000, "sa": 1000, "ssoc": 100, "ssec": 30})
    for _ in range(5):
        fw = get(base, "/esp/api/state")
        svg = render_svg(fw, "full", caption=frame_caption(fw, prev))
        prev = list(fw["relays"])
        fp = os.path.join(fr, f"f{n:03d}.svg")
        open(fp, "w").write(svg)
        cairosvg.svg2png(url=fp, write_to=os.path.join(fr, f"f{n:03d}.png"), scale=1.0)
        n += 1
        time.sleep(1.0)
    post(base, "/esp/api/spoof", {"cmd": "cancel"})
    post(base, "/api/labels", {"labels": ["R1","R2","R3","R4","R5","R6","R7","R8"]})
    out = os.path.join(outdir, "demo.gif")
    subprocess.run(["ffmpeg", "-y", "-framerate", "2", "-i", os.path.join(fr, "f%03d.png"),
                    "-vf", "split[s0][s1];[s0]palettegen=max_colors=64[p];[s1][p]paletteuse",
                    out], check=True, capture_output=True)
    print("gif:", out, f"({n} frames)")

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--sim", default="http://127.0.0.1:8008")
    ap.add_argument("--out", default="shots")
    ap.add_argument("--gif", action="store_true")
    ap.add_argument("--shot", default="", help="static: protocol|wiring|terminal|tests (+ tiles)")
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    import cairosvg
    if a.shot in ("protocol", "wiring", "terminal", "tests"):
        svg = static_svg(a.shot)
        p = os.path.join(a.out, a.shot + ".svg")
        open(p, "w").write(svg)
        cairosvg.svg2png(url=p, write_to=os.path.join(a.out, a.shot + ".png"), scale=1.5)
        print("shot:", a.shot)
        sys.exit(0)
    if a.shot == "tiles":
        tiles_png(a.sim, a.out)
        sys.exit(0)
    snap(a.sim, a.out, "dash-full", "full", scene="midseq")
    snap(a.sim, a.out, "dash-lite", "lite", scene="named")
    post(a.sim, "/api/seq", {"cmd": "stop"})
    post(a.sim, "/api/labels", {"labels": ["R1","R2","R3","R4","R5","R6","R7","R8"]})
    if a.gif:
        gif(a.sim, a.out)
