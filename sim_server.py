#!/usr/bin/env python3
"""local-wokwi sim_server.py — bms-connection-tester v2.6 standalone bench.
Serves: / = 3D bench, /esp/ = verbatim ESP dashboard (PAGE_DASH from
../src/web_ui.cpp), /board = legacy 2D, /assets/* = real meter photos,
/api/* = sim endpoints, /esp/api/* = firmware-schema compat shim.
Default GX16 pinout below is OURS until dad corrects it (5-min re-map)."""
import argparse, json, mimetypes, os, re, threading, time
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlparse, parse_qs

HOME = "/data/data/com.termux/files/home"
HERE = os.path.dirname(os.path.abspath(__file__))
FW_VERSION = "2.7"
REGS = ["03", "04", "05"]
LABELS_FILE = os.path.join(HERE, "labels.json")

def load_labels():
    try:
        labs = json.load(open(LABELS_FILE))
        if isinstance(labs, list) and len(labs) == 8:
            return [str(x)[:11] for x in labs]
    except Exception:
        pass
    return [f"R{i+1}" for i in range(8)]

def save_labels(labs):
    clean = []
    for x in labs[:8]:
        s = "".join(ch for ch in str(x) if 32 <= ord(ch) <= 126 and ch not in '"\\')[:11]
        clean.append(s or f"R{len(clean)+1}")
    while len(clean) < 8:
        clean.append(f"R{len(clean)+1}")
    json.dump(clean, open(LABELS_FILE, "w"))
    return clean

# ---- Default GX16-5 pinout (OURS — dad corrects; sim + docs read this table) ----
# J1 BUS: power + RS485. J2 LOADS: 8 relay-switched meter lines need 8 pins but
# 2x5 only gives 10 total, so: J1 carries 48V/GND/A/B + RLY_COM feed, J2 carries
# R1..R5 lines; R6..R8 ride J1 pin5? No — cleaner default: J1 = power+bus+COM,
# J2 pins 1-5 = R1..R5, and R6..R8 on a third pigtail? User said 2 connectors
# total, so default: J1 = [48V, GND, A, B, COM], J2 = [R1..R5]... still short.
# Honest default fitting 8 relays into 2x5: J1=[48V,GND,A,B,R1], J2=[R2..R6]...
# Final default: J1 = power+bus (48V/GND/A/B) + R1; J2 = R2..R6... no.
# Simplest that FITS: J1 pin5 = COM feed, J2 = R1..R5, plus R6..R8 share J1? no.
# DECISION (documented, dad-fixable): J1=[48V,GND,A,B,COM], J2=[R1,R2,R3,R4,R5],
# and R6,R7,R8 = second bank on J2 via Y-split? No — instead relays R6-R8 map to
# J1's... Stop. 10 pins, need 4 (power+bus) + 8 (relays) = 12 > 10. So 2 pins
# must dual-purpose: default COM is bussed (1 pin feeds all 8 COMs), relay lines
# = 8 pins, power+bus = 48V,GND,A,B = 4 pins → 1+8+4 = 13 > 10 still.
# Real answer: relay COM feed comes from meter side (meter powers its own lamp
# returns), tester only pulls lines LOW (open-drain style). So tester pins =
# 48V,GND,A,B (4) + 8 signal lines (8) = 12 > 10. Still over by 2.
# FINAL DEFAULT (fits, honest): J1=[48V,GND,A,B,R1], J2=[R2,R3,R4,R5,R6],
# R7+R8 on 2-pin aux pigtail (documented). Dad's real table replaces this.
GX16 = {
    "J1_BUS": {"1": "48V", "2": "GND", "3": "A (RS485)", "4": "B (RS485)", "5": "R1 (relay 1 line)"},
    "J2_LOADS": {"1": "R2", "2": "R3", "3": "R4", "4": "R5", "5": "R6"},
    "AUX_PIGTAIL": {"1": "R7", "2": "R8"},
    "note": "DEFAULT by builder; dad's 10-pin table replaces this (5-min re-map).",
}
# relay index -> connector pin label for 3D + docs
RELAY_TO_GX16 = ["J1-5", "J2-1", "J2-2", "J2-3", "J2-4", "J2-5", "AUX-1", "AUX-2"]

state = {"demo": "", "tick": 0, "running": True, "serial": [], "leds": {},
         "relays": {}, "sensors": {"t": 24.5, "h": 60.0}, "parts": [],
         "press": None, "meter_on": True, "last_bus": -99, "connected": False,
         "seq_pos": 0, "spoof_until": -1, "reg_idx": 0,
         "seq": {"running": False, "mode": 0, "count": 8, "step_ms": 500,
                 "dir": 0, "step_pos": 0, "on": [False]*8, "cycles": 0,
                 "acts": 0, "hold_until": 0},
         "spoof": {"s1": {"v": 100.0, "a": 100.0, "c": 100.0, "soc": 100, "secs": 5},
                   "s2": {"v": 88.8, "a": 88.8, "c": 88.8, "soc": 188, "secs": 10},
                   "t0": -1},
         "batch": {"meters": 0, "attempts": 0, "pass": 0, "fail": 0,
                   "attempt_open": False, "pass_latched": False,
                   "had_green": False, "red_since": 0, "link": False},
         "screen": {"page": "--", "v": "--", "a": "--", "ah": "--",
                    "soc": "--", "cells": "--", "t": "--", "name": "--"},
         "de_tx": False,
         "wifi_on": True,
         "uptime_s": 0,
         # OTA machine (mirrors main.cpp ota_check_now/ota_install_now + PAGE_DASH card)
         "ota": {"auto": False, "interval_h": 0, "latest_tag": "", "pending": False,
                 "status": "not checked", "progress": 0, "custom_url": ""},
         # energy model for flow viz (mA estimates; DAD: confirm on bench)
         "energy": {"v48": 48.0, "i_48_ma": 0, "i_12_ma": 0, "i_5_ma": 0,
                    "ab_dir": "idle", "relay_ma": [0]*8},
         "btn_hold_s": 0,
         "labels": load_labels()}
diagram_cache = {"parts": [], "connections": []}
esp_dash_cache = None
esp_update_cache = None

def esp_dash_html():
    global esp_dash_cache
    if esp_dash_cache is not None:
        return esp_dash_cache
    try:
        src = open(os.path.join(HERE, "..", "src", "web_ui.cpp")).read()
        blks = re.findall(r'PAGE_DASH\[\] PROGMEM = R"HTML\((.*?)\)HTML"', src, re.S)
        if blks:
            # v2.7: three variants (classic/lite/full); serve the FULL one
            # (longest block) — most feature rich = latest.
            esp_dash_cache = max(blks, key=len)
            return esp_dash_cache
    except Exception:
        pass
    esp_dash_cache = "<h1>ESP dashboard missing (src/web_ui.cpp not found)</h1>"
    return esp_dash_cache

def esp_update_html():
    global esp_update_cache
    if esp_update_cache is not None:
        return esp_update_cache
    try:
        src = open(os.path.join(HERE, "..", "src", "web_ui.cpp")).read()
        m = re.search(r'PAGE_UPDATE\[\] PROGMEM = R"HTML\((.*?)\)HTML"', src, re.S)
        if m:
            esp_update_cache = m.group(1)
            return esp_update_cache
    except Exception:
        pass
    esp_update_cache = "<h1>Update page missing</h1>"
    return esp_update_cache

def _factory_reset():
    """10 s hold on GPIO15 (web_factory_reset): wipe NVS sim + reboot state."""
    state["seq"] = {"running": False, "mode": 0, "count": 8, "step_ms": 500,
                    "dir": 0, "step_pos": 0, "on": [False]*8, "cycles": 0,
                    "acts": 0, "hold_until": 0}
    state["spoof"]["t0"] = -1
    state["ota"] = {"auto": False, "interval_h": 0, "latest_tag": "", "pending": False,
                    "status": "not checked", "progress": 0, "custom_url": ""}
    state["wifi_on"] = True
    state["uptime_s"] = 0
    _apply_seq_to_relays()
    log("FACTORY RESET (10 s hold): NVS wiped, rebooting... BOOT v" + FW_VERSION)

def _energy_tick():
    """Estimate rail currents each tick so 3D can size electron flow."""
    n_coils = sum(1 for x in state["seq"]["on"] if x)
    i12 = n_coils * 75  # DAD: SmartElex 12 V coil ~75 mA each (confirm)
    i5 = 180 + (120 if state["wifi_on"] else 0) + (40 if state["connected"] else 0)
    eff = i12 / 0.85 + i5 / 0.8  # buck losses, rough
    i48 = eff * 5.0 / 48.0 + 8
    e = state["energy"]
    e["i_12_ma"] = round(i12)
    e["i_5_ma"] = round(i5)
    e["i_48_ma"] = round(i48)
    e["relay_ma"] = [75 if x else 0 for x in state["seq"]["on"]]
    e["ab_dir"] = "reply" if state["de_tx"] else ("poll" if state["meter_on"] else "idle")

def log(line):
    state["serial"].append(f"[{state['tick']:05d}] {line}")
    state["serial"] = state["serial"][-120:]

def _is_real():
    d = state["demo"]
    return d.startswith("bms-connection") or d == "real"

def _set_link(on):
    state["connected"] = on
    for k in state["leds"]:
        kl = k.lower()
        if kl == "ledg" or kl == "rgb1":
            state["leds"][k] = on
        elif kl == "ledr":
            state["leds"][k] = not on

def load_demo(name):
    if name == "real":
        p = os.path.join(HERE, "..", "wokwi", "diagram.json")
        disp = f"bms-connection-tester v{FW_VERSION} (real)"
    else:
        p = os.path.join(HOME, "firmware-gig-kit", "demo-out", name, "wokwi", "diagram.json")
        disp = name
        if not os.path.exists(p):
            p = os.path.join(HERE, "..", "wokwi", "diagram.json")
            disp = f"bms-connection-tester v{FW_VERSION} (real)"
    with open(p) as f:
        diag = json.load(f)
    global diagram_cache
    diagram_cache = diag
    state["demo"] = disp
    state["parts"] = [{"id": x.get("id"), "type": x.get("type")} for x in diag.get("parts", [])]
    state["leds"] = {x["id"]: False for x in state["parts"] if "led" in x["type"] or "neopixel" in x["type"]}
    state["relays"] = {x["id"]: False for x in state["parts"] if "relay" in x["type"]}
    state["serial"] = []
    state["tick"] = 0
    state["meter_on"] = True
    state["last_bus"] = -99
    state["seq_pos"] = 0
    state["spoof_until"] = -1
    state["reg_idx"] = 0
    state["seq"] = {"running": False, "mode": 0, "count": 8, "step_ms": 500,
                    "dir": 0, "step_pos": 0, "on": [False]*8, "cycles": 0,
                    "acts": 0, "hold_until": 0}
    state["spoof"]["t0"] = -1
    state["batch"] = {"meters": 0, "attempts": 0, "pass": 0, "fail": 0,
                      "attempt_open": False, "pass_latched": False,
                      "had_green": False, "red_since": 0, "link": False}
    state["screen"] = {"page": "--", "v": "--", "a": "--", "ah": "--",
                       "soc": "--", "cells": "--", "t": "--", "name": "--"}
    state["de_tx"] = False
    state["wifi_on"] = True
    state["uptime_s"] = 0
    _set_link(False)
    log(f"BOOT {disp} — RED (no bus yet). Meter polls 0x03/04/05 every 1s.")

def _relay_ids():
    return [r for r in state["relays"]]

def _apply_seq_to_relays():
    ids = _relay_ids()
    for i, r in enumerate(ids):
        state["relays"][r] = bool(state["seq"]["on"][i]) if i < 8 else False

def _seq_start():
    sq = state["seq"]
    sq["running"] = True
    sq["step_pos"] = 0
    sq["on"] = [False]*8
    n = max(1, min(8, int(sq["count"])))
    if sq["mode"] == 1:
        for i in range(n):
            sq["on"][i] = True
            sq["acts"] += 1
        sq["hold_until"] = state["tick"] + 30
    else:
        sq["hold_until"] = 0
    b = state["batch"]
    b["attempts"] += 1
    b["attempt_open"] = True
    _apply_seq_to_relays()
    log(f"SEQ start mode={['sequential','all-on','chase'][sq['mode']]} n={n}")

def _seq_stop():
    sq = state["seq"]
    sq["running"] = False
    sq["on"] = [False]*8
    _apply_seq_to_relays()
    log("SEQ stop: all 8 relays OFF")

def _seq_tick():
    sq = state["seq"]
    if not sq["running"]:
        return
    n = max(1, min(8, int(sq["count"])))
    order = list(range(n)) if sq["dir"] == 0 else list(range(n-1, -1, -1))
    if sq["mode"] == 1:
        if state["tick"] >= sq["hold_until"]:
            sq["cycles"] += 1
            state["batch"]["pass_latched"] = True
            log(f"SEQ all-on soak done: cycle {sq['cycles']}, {sq['acts']} actuations")
            _seq_stop()
        return
    if sq["mode"] == 2:
        for i in range(8):
            sq["on"][i] = False
        pos = order[sq["step_pos"] % n]
        sq["on"][pos] = True
        sq["acts"] += 1
        sq["step_pos"] += 1
        if sq["step_pos"] % n == 0:
            sq["cycles"] += 1
            state["batch"]["pass_latched"] = True
        _apply_seq_to_relays()
        return
    if sq["step_pos"] < n:
        pos = order[sq["step_pos"]]
        sq["on"][pos] = True
        sq["acts"] += 1
        sq["step_pos"] += 1
        _apply_seq_to_relays()
        if sq["step_pos"] >= n:
            sq["cycles"] += 1
            state["batch"]["pass_latched"] = True
            log(f"SEQ sequential done R1..R{n}: cycle {sq['cycles']}")
            _seq_stop()

def _spoof_stage():
    t0 = state["spoof"]["t0"]
    if t0 < 0:
        return 0
    el = state["tick"] - t0
    s1, s2 = state["spoof"]["s1"]["secs"], state["spoof"]["s2"]["secs"]
    if el < s1:
        return 1
    if el < s1 + s2:
        return 2
    return 0

def _handle_press(pid):
    p = (pid or "").lower()
    if "spoof" in p:
        state["spoof"]["t0"] = state["tick"]
        s1 = state["spoof"]["s1"]["secs"]
        s2 = state["spoof"]["s2"]["secs"]
        log(f"SPOOF press -> stage1 {s1}s then stage2 {s2}s on 0x03")
    else:
        if state["seq"]["running"]:
            _seq_stop()
        else:
            _seq_start()

def _batch_tick(link):
    b = state["batch"]
    if not link:
        if b["link"]:
            b["link"] = False
            b["red_since"] = state["tick"]
        return
    if b["link"]:
        return
    b["link"] = True
    if not b["had_green"]:
        b["had_green"] = True
        b["meters"] += 1
        b["attempt_open"] = False
        b["pass_latched"] = False
        return
    if (state["tick"] - b["red_since"]) < 3:
        return
    if state["seq"]["running"]:
        return
    if b["attempt_open"]:
        if b["pass_latched"]:
            b["pass"] += 1
        else:
            b["fail"] += 1
        b["attempt_open"] = False
        b["pass_latched"] = False
    b["meters"] += 1
    log(f"BATCH: meter #{b['meters']} seated (pass {b['pass']} / fail {b['fail']})")

def _tick_real():
    if state["meter_on"]:
        reg = REGS[state["reg_idx"] % 3]
        state["reg_idx"] += 1
        ck = (0x10000 - (int(reg, 16) + 0x00)) & 0xFFFF
        state["last_bus"] = state["tick"]
        _set_link(True)
        state["de_tx"] = True
        log(f"[METER] poll DD A5 {reg} 00 {ck:04X} 77 -> bus")
        st = _spoof_stage()
        sc = state["screen"]
        sc["page"] = reg
        if reg == "03" and st:
            v = state["spoof"][f"s{st}"]
            sc.update({"v": f"{v['v']:.1f}", "a": f"{v['a']:.1f}",
                       "soc": str(v["soc"]), "ah": "100", "cells": "14", "t": "25.0"})
            log(f"[DUT] reply 0x03 SPOOF stage{st}: {v['v']:.1f}V {v['soc']}% (meter screen updates)")
        elif reg == "03":
            sc.update({"v": "52.0", "a": "0.0", "ah": "100", "soc": "100",
                       "cells": "14", "t": "25.0"})
            log("[DUT] reply 0x03 basic: 52.0V 100Ah 100% 14 cells 25.0C (GREEN)")
        elif reg == "04":
            log("[DUT] reply 0x04 cells: 14x3714mV (GREEN)")
        else:
            sc["name"] = "TEST-14S100A"
            log("[DUT] reply 0x05 name: TEST-14S100A (GREEN)")
    else:
        state["de_tx"] = False
        if state["tick"] - state["last_bus"] > 2 and state["connected"]:
            _set_link(False)
            log("[DUT] bus silent 2s -> RED (check A/B swap, GND, meter power)")
    _batch_tick(state["connected"])
    _seq_tick()
    if state["press"]:
        _handle_press(state["press"])
        state["press"] = None
    _energy_tick()
    for r, on in list(state["relays"].items()):
        lamp = "r" + "".join(ch for ch in r if ch.isdigit())
        if lamp in state["leds"]:
            state["leds"][lamp] = on

def engine():
    while True:
        time.sleep(1.0)
        if not state["running"]:
            continue
        state["tick"] += 1
        state["uptime_s"] += 1
        if _is_real():
            _tick_real()
            continue
        if state["press"]:
            state["press"] = None

# ---- firmware-schema compat: what the REAL dashboard JS expects ----
def fw_state():
    sq, b, sc = state["seq"], state["batch"], state["screen"]
    st = _spoof_stage()
    s1, s2 = state["spoof"]["s1"], state["spoof"]["s2"]
    o = state["ota"]
    # v2.7 meter readout: mirrors handle_state() — golden or active spoof stage
    if st == 1:
        mv, ma, msoc = int(s1["v"]*10), int(s1["a"]*10), int(s1["soc"])
    elif st != 0:
        mv, ma, msoc = int(s2["v"]*10), int(s2["a"]*10), int(s2["soc"])
    else:
        mv, ma, msoc = 520, 0, 100
    return {
        "fw": FW_VERSION, "link": state["connected"], "running": sq["running"],
        "spoof": st != 0, "stage": st, "cycles": sq["cycles"], "acts": sq["acts"],
        "relays": [1 if x else 0 for x in sq["on"]],
        "cfg": {
            "m_met": b["meters"], "m_att": b["attempts"], "m_ps": b["pass"], "m_fl": b["fail"],
            "rmode": sq["mode"], "nrel": sq["count"], "step": sq["step_ms"],
            "hseq": 30000, "swp": 3, "hall": 300000, "bmode": 0, "alow": 1,
            "loop": 0, "cpause": 2000, "clim": 0, "stag": 50, "dir": sq["dir"],
            "auto": 0, "sena": 1, "sinv": 0, "spin": 21,
            "sv": int(s1["v"]*10), "sa": int(s1["a"]*10), "sc": int(s1["c"]*10),
            "ssoc": int(s1["soc"]), "ssec": int(s1["secs"]),
            "s2v": int(s2["v"]*10), "s2a": int(s2["a"]*10), "s2c": int(s2["c"]*10),
            "s2soc": int(s2["soc"]),             "s2sec": int(s2["secs"]),
            "mv": mv, "ma": ma, "msoc": msoc,
            "sta": 0, "sta_en": 0, "sta_ssid": "",
            "ota_auto": 1 if o["auto"] else 0, "ota_latest": o["latest_tag"],
            "ota_pending": 1 if o["pending"] else 0, "ota_status": o["status"],
            "ota_int_h": o["interval_h"], "variant": "sim", "flash_kb": 8192, "sketch_free": 1000000,
            "heap": 200000, "psram": 0, "uptime_s": state["uptime_s"],
            "boot": 1, "reset": "SIM", "rssi": 0, "sta_ip": "", "sta_mac": "",
            "sta_test": 0, "sta_test_msg": "not tested (sim)", "ota_url": "",
            "lbl0": state["labels"][0], "lbl1": state["labels"][1],
            "lbl2": state["labels"][2], "lbl3": state["labels"][3],
            "lbl4": state["labels"][4], "lbl5": state["labels"][5],
            "lbl6": state["labels"][6], "lbl7": state["labels"][7],
            "ap_ssid": "BMS-Tester", "ap_ch": 6,
        },
    }

def ota_cmp(a, b):
    """Host port of ota_cmp_version (ota.h): tolerates leading 'v'."""
    def parts(s):
        s = str(s).lstrip("vV")
        out = []
        for p in s.split("."):
            out.append(int(p) if p.isdigit() else 0)
        return out
    pa, pb = parts(a), parts(b)
    for x, y in zip(pa + [0]*3, pb + [0]*3):
        if x != y:
            return 1 if x > y else -1
    return 0

def ota_live_check():
    """Real GitHub check like the box does (api.github.com releases/latest).
    Returns (tag, asset_names) or (None, []) offline/failure."""
    try:
        import urllib.request
        req = urllib.request.Request(
            "https://api.github.com/repos/bm-a/bms-connection-tester/releases/latest",
            headers={"User-Agent": "bms-tester-sim", "Accept": "application/vnd.github+json"})
        d = json.load(urllib.request.urlopen(req, timeout=10))
        return d.get("tag_name", ""), [x.get("name", "") for x in d.get("assets", [])]
    except Exception as e:
        log(f"OTA check: GitHub unreachable ({type(e).__name__}) — sim default")
        return None, []

def handle_esp_post(path, data):
    """Drive the sim from the REAL dashboard's POSTs. Returns (ok, err)."""
    if path == "/api/relay":
        try: i = int(data.get("i", -1)); on = bool(int(data.get("on", 1)))
        except (TypeError, ValueError): return False, "bad args"
        n = max(1, min(8, int(state["seq"]["count"])))
        if state["seq"]["running"]: return False, "STOP the sequence first"
        if not (0 <= i < n): return False, "relay outside count"
        state["seq"]["on"][i] = on
        _apply_seq_to_relays()
        log(f"ESP relay R{i+1} -> {'ON' if on else 'OFF'}")
        return True, ""
    if path == "/api/seq":
        c = str(data.get("cmd", ""))
        if c == "start":
            if state["seq"]["running"]: return False, "already running"
            _seq_start(); return True, ""
        if c == "stop": _seq_stop(); return True, ""
        return False, "cmd=start|stop"
    if path == "/api/config":
        sq = state["seq"]
        try:
            if "rmode" in data: sq["mode"] = max(0, min(2, int(data["rmode"])))
            if "nrel" in data: sq["count"] = max(1, min(8, int(data["nrel"])))
            if "step" in data: sq["step_ms"] = max(100, int(data["step"]))
            if "dir" in data: sq["dir"] = 1 if int(data["dir"]) else 0
        except (TypeError, ValueError):
            return False, "bad values"
        labs = [state["labels"][i] for i in range(8)]
        touched = False
        for i in range(8):
            if f"lbl{i}" in data:
                labs[i] = str(data[f"lbl{i}"])
                touched = True
        if touched:
            state["labels"] = save_labels(labs)
            log("ESP relay labels saved (labels.json, NVS on HW)")
        log(f"ESP config: mode={sq['mode']} n={sq['count']} step={sq['step_ms']}ms")
        return True, ""
    if path == "/api/spoof":
        c = str(data.get("cmd", "fire"))
        if c in ("fire", "save", "trig"):
            try:
                if "sv" in data: state["spoof"]["s1"]["v"] = float(data["sv"])/10.0
                if "sa" in data: state["spoof"]["s1"]["a"] = float(data["sa"])/10.0
                if "sc" in data: state["spoof"]["s1"]["c"] = float(data["sc"])/10.0
                if "ssoc" in data: state["spoof"]["s1"]["soc"] = int(data["ssoc"])
                if "ssec" in data: state["spoof"]["s1"]["secs"] = int(data["ssec"])
                if "s2v" in data: state["spoof"]["s2"]["v"] = float(data["s2v"])/10.0
                if "s2a" in data: state["spoof"]["s2"]["a"] = float(data["s2a"])/10.0
                if "s2c" in data: state["spoof"]["s2"]["c"] = float(data["s2c"])/10.0
                if "s2soc" in data: state["spoof"]["s2"]["soc"] = int(data["s2soc"])
                if "s2sec" in data: state["spoof"]["s2"]["secs"] = int(data["s2sec"])
            except (TypeError, ValueError): return False, "bad values"
            if c == "fire":
                state["spoof"]["t0"] = state["tick"]
                log("ESP spoof FIRE -> meter screen jumps to stage values")
            else:
                log("ESP spoof saved (sim)")
            return True, ""
        if c == "cancel":
            state["spoof"]["t0"] = -1
            log("ESP spoof cancelled")
            return True, ""
        return False, "cmd=fire|save|cancel"
    if path == "/api/meter":
        if str(data.get("cmd", "")) == "reset":
            b = state["batch"]
            for k in ("meters", "attempts", "pass", "fail"): b[k] = 0
            b["attempt_open"] = b["pass_latched"] = False
            log("ESP day reset: counters cleared")
            return True, ""
        return False, "cmd=reset"
    if path == "/api/cmd":
        c = str(data.get("cmd", "")).strip()
        up = c.upper()
        if up == "STATUS?": log(("GREEN " if state["connected"] else "RED ") + FW_VERSION)
        elif up == "START":
            if not state["seq"]["running"]: _seq_start()
        elif up == "STOP": _seq_stop()
        elif up == "FIRE":
            state["spoof"]["t0"] = state["tick"]; log("ESP console FIRE")
        elif up == "CANCEL": state["spoof"]["t0"] = -1
        elif up == "DAYRESET":
            b = state["batch"]
            for k in ("meters", "attempts", "pass", "fail"): b[k] = 0
        elif up in ("VERSION", "UPTIME"):
            log(f"{up}: v{FW_VERSION} up {state['uptime_s']}s")
        elif up in ("REBOOT", "RESET"):
            log(f"ESP console {up} (sim: ignored, HW reboots)")
        elif up == "HELP": log("cmds: START STOP FIRE CANCEL DAYRESET STATUS UPTIME VERSION")
        else: log(f"console: {c}")
        return True, ""
    if path in ("/api/admin",):
        c = str(data.get("cmd", ""))
        if c == "reboot":
            state["uptime_s"] = 0
            log("ESP admin REBOOT (sim: uptime reset, HW reboots)")
        elif c == "reset":
            _factory_reset()
        elif c == "reset_keepwifi":
            keep = state["wifi_on"]
            _factory_reset()
            state["wifi_on"] = keep
            log("ESP admin reset_keepwifi (sim)")
        elif c == "bootcount_reset":
            log("ESP admin bootcount reset (sim)")
        else:
            log("ESP admin save (AP/STA/admin, sim accepts any pass — HW enforces)")
        return True, ""
    if path == "/api/ota":
        o = state["ota"]
        c = str(data.get("cmd", ""))
        if "ota_url" in data:
            o["custom_url"] = str(data["ota_url"])
            log(f"ESP custom firmware URL saved: {o['custom_url'] or '(GitHub releases)'}")
        if "ota_int_h" in data:
            try: o["interval_h"] = int(data["ota_int_h"])
            except (TypeError, ValueError): pass
        if "ota_auto" in data:
            o["auto"] = bool(int(data["ota_auto"]))
        if c == "check":
            o["status"] = "checking..."
            tag, assets = ota_live_check()
            if tag:
                o["latest_tag"] = tag
                o["assets"] = assets
                o["pending"] = ota_cmp(tag, FW_VERSION) > 0
                want = {"firmware.bin", "n16r8-firmware.bin"} & set(assets)
                o["status"] = (f"update available ({', '.join(sorted(want))} present)"
                               if o["pending"] and want else
                               "up to date" if not o["pending"] else
                               "update available BUT no firmware asset on GH (bins pending bench-PC build)")
                log(f"ESP OTA check: releases/latest -> {tag} assets={len(assets)} => {o['status']}")
            else:
                o["latest_tag"] = "v2.6"
                o["pending"] = False
                o["status"] = "up to date (sim offline default)"
        elif c == "install":
            if not o["pending"]:
                log("ESP OTA install: nothing pending (sim) — check first")
            elif not ({"firmware.bin", "n16r8-firmware.bin"} & set(o.get("assets", []))):
                o["status"] = "install http 404"
                log("ESP OTA install: install http 404 (sim matches HW — no firmware asset on GH yet, box keeps running)")
            else:
                o["status"] = "installing..."
                o["progress"] = 100
                log("ESP OTA install: streamed + verified (sim) — rebooting...")
                state["uptime_s"] = 0
                o["pending"] = False
                o["status"] = "up to date"
        elif c == "url_upgrade":
            if not o["custom_url"].startswith("http"):
                return False, "bad custom url"
            log(f"ESP OTA upgrade from URL: {o['custom_url']} (sim: gates pass)")
        return True, ""
    if path == "/api/sta":
        c = str(data.get("cmd", ""))
        if c == "test":
            log("ESP STA uplink test: joining (sim, <=30 s on HW)... result: sim-ok, RSSI -55 dBm, drops back to AP-only")
        else:
            log("ESP STA save (sim)")
        return True, ""
    if path == "/api/restore":
        log("ESP config restore: validated + applied (sim, passwords never imported)")
        return True, ""
    if path in ("/api/backup",):
        return True, ""
    return False, "unknown"

class H(BaseHTTPRequestHandler):
    def _json(self, obj):
        b = json.dumps(obj).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)
    def _html(self, b):
        if isinstance(b, str): b = b.encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)
    def do_GET(self):
        u = urlparse(self.path)
        p = u.path
        if p == "/":
            with open(os.path.join(HERE, "bench3d.html"), "rb") as f: b = f.read()
            return self._html(b)
        if p == "/board":
            with open(os.path.join(HERE, "board.html"), "rb") as f: b = f.read()
            return self._html(b)
        if p in ("/esp", "/esp/"):
            if not state["wifi_on"]:
                return self._html("<body style='background:#0f172a;color:#e2e8f0;font-family:sans-serif;padding:40px'><h2>AP OFF</h2><p>GPIO18 grounded — WiFi AP + portal + server down (real HW behavior). Release the WiFi toggle to restore.</p></body>")
            return self._html(esp_dash_html())
        if p in ("/esp/update", "/esp/update/"):
            if not state["wifi_on"]:
                self.send_error(503, "AP OFF (GPIO18)")
                return
            return self._html(esp_update_html())
        if p == "/esp/api/state":
            if not state["wifi_on"]:
                self.send_error(503, "AP OFF (GPIO18)")
                return
            return self._json(fw_state())
        if p == "/esp/api/backup":
            if not state["wifi_on"]:
                self.send_error(503, "AP OFF (GPIO18)")
                return
            fw = fw_state()
            return self._json({"config": 2, "relays": {"mode": fw["cfg"]["rmode"], "count": fw["cfg"]["nrel"]},
                               "spoof": {"s1": state["spoof"]["s1"], "s2": state["spoof"]["s2"]},
                               "meta": {"fw": FW_VERSION, "sim": True}})
        if p == "/esp/api/uprog":
            return self._json({"progress": state["ota"]["progress"]})
        if p == "/api/state":
            return self._json(state)
        if p == "/api/fwstate":
            return self._json(fw_state())
        if p == "/api/diagram":
            return self._json(diagram_cache)
        if p == "/api/gx16":
            return self._json({"gx16": GX16, "relay_to_gx16": RELAY_TO_GX16})
        if p == "/api/demo":
            q = parse_qs(u.query)
            load_demo(q.get("name", ["real"])[0])
            return self._json({"ok": True, "demo": state["demo"]})
        if p.startswith("/assets/"):
            name = os.path.basename(p)
            mapping = {"meter-cluster.jpg": "IMG_0341.jpeg",
                       "meter-segments.jpg": "1411bb7a-d99e-4885-8ea0-12714b984a5c.jpeg"}
            src = os.path.join(HERE, "..", "Actual Meter Image", mapping.get(name, name))
            if os.path.exists(src):
                with open(src, "rb") as f: b = f.read()
                self.send_response(200)
                self.send_header("Content-Type", mimetypes.guess_type(src)[0] or "image/jpeg")
                self.send_header("Content-Length", str(len(b)))
                self.send_header("Cache-Control", "max-age=3600")
                self.end_headers()
                self.wfile.write(b)
                return
            self.send_error(404)
            return
        self.send_error(404)
    def do_POST(self):
        u = urlparse(self.path)
        p = u.path
        n = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(n) if n else b"{}"
        try: data = json.loads(body or b"{}")
        except Exception: data = {}
        # /esp/api/* compat shim (real dashboard paths)
        if p.startswith("/esp/api/"):
            real = p[len("/esp"):]
            ok, err = handle_esp_post(real, data)
            if real == "/api/cmd":
                return self._json({"ok": True, "out": state["serial"][-1] if state["serial"] else "ok"})
            if not ok:
                return self._json({"ok": False, "err": err})
            return self._json({"ok": True})
        if p == "/api/press":
            state["press"] = data.get("id", "btn")
            log(f"press {state['press']}")
            return self._json({"ok": True})
        if p == "/api/hold":
            # press-and-HOLD (factory reset path: GPIO15 held 10 s)
            ident = str(data.get("id", "btn"))
            try: secs = float(data.get("secs", 0))
            except (TypeError, ValueError): secs = 0
            if "btn" in ident.lower() and secs >= 10:
                _factory_reset()
                return self._json({"ok": True, "reset": True})
            state["press"] = ident
            log(f"hold {ident} {secs}s (need 10 s for factory reset)")
            return self._json({"ok": True, "reset": False})
        if p in ("/esp/update", "/esp/update/") or p == "/api/upload":
            # browser .bin upload (real page POSTs multipart; sim takes JSON or raw name)
            name = str(data.get("name", data.get("filename", "firmware.bin")))
            if not name.endswith(".bin"):
                return self._json({"ok": False, "err": "not a .bin (Tasmota gate: wrong file changes nothing)"})
            log(f"FW upload {name}: magic 0xE9 ok, variant sim ok, budget ok — flashed (sim), rebooting...")
            state["uptime_s"] = 0
            return self._json({"ok": True})
        if p == "/api/run":
            state["running"] = bool(data.get("running", True))
            return self._json({"ok": True, "running": state["running"]})
        if p == "/api/meter":
            state["meter_on"] = bool(data.get("on", True))
            log(f"meter {'powered' if state['meter_on'] else 'unplugged (watch RED in ~2s)'}.")
            return self._json({"ok": True, "meter_on": state["meter_on"]})
        if p == "/api/wifi":
            state["wifi_on"] = bool(data.get("on", True))
            log(f"WiFi {'AP UP (GPIO18 released)' if state['wifi_on'] else 'AP OFF (GPIO18 grounded — page down, USB alive)'}.")
            return self._json({"ok": True, "wifi_on": state["wifi_on"]})
        if p == "/api/cmd":
            cmd = str(data.get("cmd", "")).strip()
            if cmd == "STATUS?": log(("GREEN " if state["connected"] else "RED ") + FW_VERSION)
            else: log(f"unknown cmd: {cmd}")
            return self._json({"ok": True})
        if p == "/api/relay":
            try: i, on = int(data.get("i", 0)), bool(data.get("on", True))
            except (TypeError, ValueError): return self._json({"ok": False, "err": "bad args"})
            if state["seq"]["running"]: return self._json({"ok": False, "err": "STOP the sequence first"})
            if 0 <= i < 8:
                state["seq"]["on"][i] = on
                _apply_seq_to_relays()
                log(f"WEB relay R{i+1} -> {'ON' if on else 'OFF'} ({RELAY_TO_GX16[i]})")
                return self._json({"ok": True})
            return self._json({"ok": False, "err": "relay 0..7"})
        if p == "/api/seq":
            c = str(data.get("cmd", ""))
            if c == "start":
                if state["seq"]["running"]: return self._json({"ok": False, "err": "already running"})
                _seq_start(); return self._json({"ok": True})
            if c == "stop": _seq_stop(); return self._json({"ok": True})
            return self._json({"ok": False, "err": "cmd=start|stop"})
        if p == "/api/spoof":
            c = str(data.get("cmd", "fire"))
            if c in ("fire", "save"):
                for st in ("s1", "s2"):
                    for k in ("v", "a", "c", "soc", "secs"):
                        if st == "s1" and k in data:
                            try: state["spoof"]["s1"][k] = float(data[k])
                            except (TypeError, ValueError): pass
                        fk = {"v": "s2v", "a": "s2a", "c": "s2c", "soc": "s2soc", "secs": "s2sec"}[k]
                        if st == "s2" and fk in data:
                            try: state["spoof"]["s2"][k] = float(data[fk])
                            except (TypeError, ValueError): pass
                if c == "fire":
                    state["spoof"]["t0"] = state["tick"]
                    log("WEB spoof FIRE: stage values live on 0x03 + meter screen")
                else: log("WEB spoof saved (not fired)")
                return self._json({"ok": True})
            if c == "cancel":
                state["spoof"]["t0"] = -1
                log("WEB spoof cancelled")
                return self._json({"ok": True})
            return self._json({"ok": False, "err": "cmd=fire|save|cancel"})
        if p == "/api/config":
            sq = state["seq"]
            try:
                if "rmode" in data: sq["mode"] = max(0, min(2, int(data["rmode"])))
                if "nrel" in data: sq["count"] = max(1, min(8, int(data["nrel"])))
                if "step" in data: sq["step_ms"] = max(100, int(data["step"]))
                if "dir" in data: sq["dir"] = 1 if int(data["dir"]) else 0
            except (TypeError, ValueError): return self._json({"ok": False, "err": "bad values"})
            log(f"WEB config: mode={sq['mode']} n={sq['count']} step={sq['step_ms']}ms")
            return self._json({"ok": True})
        if p == "/api/labels":
            labs = data.get("labels", [])
            if not isinstance(labs, list) or len(labs) != 8:
                return self._json({"ok": False, "err": "labels: 8 names"})
            state["labels"] = save_labels(labs)
            log(f"relay labels saved: {', '.join(state['labels'])}")
            return self._json({"ok": True, "labels": state["labels"]})
        if p == "/api/dayreset":
            b = state["batch"]
            for k in ("meters", "attempts", "pass", "fail"): b[k] = 0
            b["attempt_open"] = b["pass_latched"] = False
            log("WEB day reset: counters cleared")
            return self._json({"ok": True})
        self.send_error(404)
    def log_message(self, *a):
        pass

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--demo", default="real")
    a = ap.parse_args()
    load_demo(a.demo)
    threading.Thread(target=engine, daemon=True).start()
    print(f"local-wokwi v{FW_VERSION} -> http://localhost:{a.port}  demo={state['demo']}")
    HTTPServer(("127.0.0.1", a.port), H).serve_forever()
