import json, urllib.request, time, os
D = 'http://127.0.0.1:8008'
# Env-dependent checks (need sibling firmware sources or live internet)
# SKIP instead of FAIL when the environment can't provide them.
CI = os.environ.get("CI") == "true" or not os.path.exists(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src", "web_ui.cpp"))

def get(p):
    try:
        return True, urllib.request.urlopen(D + p, timeout=10).read()
    except Exception as e:
        return False, e

def post(p, b):
    try:
        req = urllib.request.Request(D + p, data=json.dumps(b).encode(),
                                     headers={'Content-Type': 'application/json'})
        return True, json.load(urllib.request.urlopen(req, timeout=10))
    except Exception as e:
        return False, e

R, S = [], []
def check(n, c, i=""):
    R.append(bool(c)); print("PASS" if c else "FAIL", n, i)
def skip(n, i=""):
    S.append(n); print("SKIP", n, i)

ok, s = get('/api/state')
if not ok:
    print("FAIL boot: server not reachable", s); raise SystemExit(1)
s = json.loads(s)
check("boot 2.7", "bms-connection-tester v2.7" in s['demo'], s['demo'])
ok, e = get('/esp/')
if CI and (not ok or 'bench_r0' not in e.decode(errors="replace")):
    skip("esp FULL bench", "needs sibling firmware src (local only)")
else:
    e = e.decode()
    check("esp FULL bench", 'bench_r0' in e and 'flowAB' in e, len(e))
ok, r = post('/api/labels', {'labels': ['HORN','L','F','P','R5','R6','R7','R8']})
check("labels api", ok and r['ok'])
ok, f = get('/esp/api/state')
f = json.loads(f) if ok else {}
check("fw labels+mv", ok and f['cfg']['lbl0'] == 'HORN' and f['cfg']['mv'] == 520,
      (f.get('cfg', {}).get('lbl0'), f.get('cfg', {}).get('mv')) if ok else "unreachable")
post('/api/seq', {'cmd': 'start'})
ok, r = post('/api/relay', {'i': 0, 'on': True})
check("relay lock", ok and r == {'ok': False, 'err': 'STOP the sequence first'})
post('/api/seq', {'cmd': 'stop'})
ok, r = post('/esp/api/ota', {'cmd': 'check'})
check("ota", ok and r == {'ok': True})
ok, a = post('/api/upload', {'name': 'x.bin'})
ok2, b = post('/api/upload', {'name': 'x.txt'})
check("upload ok+reject", ok and a == {'ok': True} and ok2 and b['ok'] is False)
ok, r = post('/api/hold', {'id': 'btn', 'secs': 10})
check("hold-reset", ok and r == {'ok': True, 'reset': True})
post('/api/labels', {'labels': ['R1','R2','R3','R4','R5','R6','R7','R8']})
# live-GH OTA check (real api.github.com, like the box) — env-dependent
try:
    ok, r = post('/esp/api/ota', {'cmd': 'check'})
    ok2, f = get('/esp/api/state')
    f = json.loads(f) if ok2 else {}
    if ok and ok2 and r['ok'] and f['cfg']['ota_latest'] == 'v2.7':
        check("live OTA check", True, f['cfg']['ota_status'])
    elif CI:
        skip("live OTA check", "needs live api.github.com")
    else:
        check("live OTA check", False, (r, f.get('cfg', {}).get('ota_status')))
except Exception as e:
    if CI:
        skip("live OTA check", e)
    else:
        check("live OTA check", False, e)
ok, h = get('/')
check("relay row html", ok and 'rboard' in h.decode(errors="replace") and 'saveNames' in h.decode(errors="replace"))
print(f"{sum(R)}/{len(R)} sim checks passed, {len(S)} skipped")
raise SystemExit(1 if sum(R) != len(R) else 0)
