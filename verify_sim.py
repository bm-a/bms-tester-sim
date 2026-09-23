import json, urllib.request, time
D = 'http://127.0.0.1:8008'
def post(p, b):
    req = urllib.request.Request(D + p, data=json.dumps(b).encode(),
                                 headers={'Content-Type': 'application/json'})
    return json.load(urllib.request.urlopen(req))
R = []
def check(n, c, i=""):
    R.append(bool(c)); print("PASS" if c else "FAIL", n, i)
s = json.load(urllib.request.urlopen(D + '/api/state'))
check("boot 2.7", "bms-connection-tester v2.7" in s['demo'], s['demo'])
e = urllib.request.urlopen(D + '/esp/').read().decode()
check("esp FULL bench", 'bench_r0' in e and 'flowAB' in e, len(e))
check("labels api", post('/api/labels', {'labels': ['HORN','L','F','P','R5','R6','R7','R8']})['ok'])
f = json.load(urllib.request.urlopen(D + '/esp/api/state'))
check("fw labels+mv", f['cfg']['lbl0'] == 'HORN' and f['cfg']['mv'] == 520, (f['cfg']['lbl0'], f['cfg']['mv']))
post('/api/seq', {'cmd': 'start'})
check("relay lock", post('/api/relay', {'i': 0, 'on': True}) == {'ok': False, 'err': 'STOP the sequence first'})
post('/api/seq', {'cmd': 'stop'})
check("ota", post('/esp/api/ota', {'cmd': 'check'}) == {'ok': True})
check("upload ok+reject", post('/api/upload', {'name': 'x.bin'}) == {'ok': True} and post('/api/upload', {'name': 'x.txt'})['ok'] is False)
check("hold-reset", post('/api/hold', {'id': 'btn', 'secs': 10}) == {'ok': True, 'reset': True})
post('/api/labels', {'labels': ['R1','R2','R3','R4','R5','R6','R7','R8']})
# live-GH OTA check (real api.github.com, like the box)
r = post('/esp/api/ota', {'cmd': 'check'})
f = json.load(urllib.request.urlopen(D + '/esp/api/state'))
check("live OTA check", r['ok'] and f['cfg']['ota_latest'] == 'v2.7', f['cfg']['ota_status'])
h = urllib.request.urlopen(D + '/').read().decode()
check("relay row html", 'rboard' in h and 'saveNames' in h)
print(f"{sum(R)}/{len(R)} sim checks passed")
