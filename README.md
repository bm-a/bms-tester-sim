# local-wokwi — offline browser simulator for this BMS tester

Your own mini-Wokwi that runs on your phone / laptop with **no internet**.
Same idea as wokwi.com: virtual board + LEDs + buttons + relays + serial log,
driven by the real `../wokwi/diagram.json` wiring in this repo.

## Files

| File | What it is |
|---|---|
| `sim_server.py` | Localhost server (stdlib Python only, no pip packages). Loads `../wokwi/diagram.json`, ticks the simulation ~1/s, serves the UI + JSON API. |
| `bench3d.html` | **Default page (`/`).** True-3D bench (Three.js CDN): one tester ESP32-S3 + MAX485 module (DE direction LED) + e-rickshaw **meter device with live LCD** (V/A/Ah/SOC/cells/temp per polled register, spoof values appear on screen) + 8 relay modules with coil lamps + load lamps, color-coded tube wires, poll/reply pulse packets, orbit/zoom, tap-to-press buttons/meter keys/relay boxes. Below it: a fully interactive mirror of the real ESP32 webpage (relay grid, meters-today, sequence config, spoof card, console) + serial pane. `/board` keeps the old flat 2D view. |
| `board.html` | Legacy flat 2D bench (Wokwi-style SVG). Kept at `/board`. |

## Run (30 seconds)

```sh
cd ~/bms-connection-tester/local-wokwi
python3 sim_server.py --port 8000
```

Then open in any browser (phone Chrome works, offline OK):

```
http://localhost:8000
```

- ▶ **Play** / ⏸ **Stop** the sim clock.
- **Relay board row**: 8 glowing tiles (tap = force ON/OFF, IDLE-only lock
  like the box) + START/STOP + editable names that persist to
  `labels.json` (mirrors NVS labels on hardware) and sync into the `/esp/`
  page tiles.
- Tap any 3D **button** part (BUTTON / SPOOF / WiFi toggle / OTA check /
  FACTORY RESET-hold) — relays sequence, serial logs it.
- **Serial** pane shows the meter polling `DD A5 03/04/05 …` and the tester replying `52.0V 100Ah 100%`, green LED on.
- Dropdown loads the other portfolio demos too (`portfolio-01-relay-web`, `portfolio-02-climate-mqtt`, `portfolio-03-bms-rs485` from `~/firmware-gig-kit/demo-out/`).

## What it simulates (BMS tester mapping)

From `../wokwi/diagram.json` + `../wokwi/README.md`:

- `dut` (ESP32-S3) + `meter` (second S3 as virtual meter, UART cross-wired 17↔16) → serial shows the poll/reply loop.
- `ledG` / `ledR` → green = traffic seen / link good, red = bus silent (same semantics as the real box).
- `btn` (GPIO15) → runs the relay sequence on `rl1…rl8`; `spoofbtn` (GPIO21) → 10 s test values on the meter console.
- `rl1…rl8` (GPIO 5/6/7/8/9/12/13/14) → ON/OFF states shown live.

## Honest limits

- Runs firmware **logic models**, not the compiled ESP32 binary — same class of limit as Wokwi itself (which also doesn't emulate WiFi; see `../wokwi/README.md`).
- For bit-exact binary boot, use `~/esp32s3-qemu-arm64` on real Linux (QEMU JIT can't run inside Termux proot).
- For proof-grade firmware checks, use the repo's real gates: `pio test -e native`, `sh run_tests.sh`, `sh tools/check_ino.sh`.

## Why it exists (client trust)

Screen-record 30 s of Play ▶ + serial `BOOT …` + green LED and attach it to the
Fiverr/Upwork delivery ZIP. Buyers who *see* the sim running approve 10× faster
than buyers who only get a `.bin`. See `~/firmware-gig-kit/GIGS.md` for the gig pack.
