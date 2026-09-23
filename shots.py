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

def render_svg(fw, variant="full"):
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
    svg = (f'<svg xmlns="http://www.w3.org/2000/svg" width="680" height="{H}" font-family="monospace">'
           f'<rect width="680" height="{H}" fill="#0f172a"/>'
           f'<text x="12" y="34" fill="#e2e8f0" font-size="24">⚡ BMS Tester</text>'
           f'<text x="220" y="34" fill="#94a3b8" font-size="13">v{esc(fw.get("fw","?"))} sim snapshot</text>'
           f'<rect x="380" y="12" width="130" height="26" rx="13" fill="{linkpill}"/>'
           f'<text x="445" y="30" fill="#fff" font-size="13" text-anchor="middle">{linktxt}</text>'
           f'<text x="520" y="30" fill="#94a3b8" font-size="12">cyc {fw.get("cycles",0)} · act {fw.get("acts",0)}</text>'
           f'{bench}'
           f'<text x="12" y="{head_y-8}" fill="#93c5fd" font-size="14">RELAYS</text>'
           + tiles +
           f'<text x="12" y="{H-12}" fill="#64748b" font-size="11">meters {c.get("m_met",0)} · attempts {c.get("m_att",0)} · pass {c.get("m_ps",0)} · fail {c.get("m_fl",0)} · rendered from live /esp/api/state</text>'
           f'</svg>')
    return svg

def snap(base, outdir, name, variant="full"):
    import cairosvg
    fw = get(base, "/esp/api/state")
    svg = render_svg(fw, variant)
    p = os.path.join(outdir, name + ".svg")
    open(p, "w").write(svg)
    cairosvg.svg2png(url=p, write_to=os.path.join(outdir, name + ".png"), scale=1.5)
    print("shot:", name)

def gif(base, outdir):
    import cairosvg
    fr = os.path.join(outdir, "frames")
    os.makedirs(fr, exist_ok=True)
    post(base, "/api/config", {"rmode": 0, "nrel": 8})
    post(base, "/api/seq", {"cmd": "stop"})
    post(base, "/api/seq", {"cmd": "start"})
    n = 0
    for _ in range(12):
        fw = get(base, "/esp/api/state")
        svg = render_svg(fw, "full")
        fp = os.path.join(fr, f"f{n:03d}.svg")
        open(fp, "w").write(svg)
        cairosvg.svg2png(url=fp, write_to=os.path.join(fr, f"f{n:03d}.png"), scale=1.0)
        n += 1
        if not fw["running"] and fw["cycles"] >= 1:
            break
        time.sleep(1.0)
    post(base, "/esp/api/spoof", {"cmd": "fire", "sv": 1000})
    for _ in range(4):
        fw = get(base, "/esp/api/state")
        svg = render_svg(fw, "full")
        fp = os.path.join(fr, f"f{n:03d}.svg")
        open(fp, "w").write(svg)
        cairosvg.svg2png(url=fp, write_to=os.path.join(fr, f"f{n:03d}.png"), scale=1.0)
        n += 1
        time.sleep(1.0)
    post(base, "/esp/api/spoof", {"cmd": "cancel"})
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
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    snap(a.sim, a.out, "dash-full", "full")
    snap(a.sim, a.out, "dash-lite", "lite")
    if a.gif:
        gif(a.sim, a.out)
