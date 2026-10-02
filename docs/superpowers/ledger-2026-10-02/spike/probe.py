"""probe.py PORT METHOD PATH [header:value ...] -> what the witness saw, and what the app got."""
import json, subprocess, sys, uuid, urllib.request, urllib.error
port, method, path, *hs = sys.argv[1:]
tid = uuid.uuid4().hex[:8]
headers = {"X-Test-Id": tid}
body = None
for h in hs:
    k, _, v = h.partition(":")
    if k == "BODY": body = v.encode(); continue
    headers[k] = v
class NoRedir(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k): return None
req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", data=body, method=method, headers={"Host": f"localhost:{port}", **headers})
try:
    r = urllib.request.build_opener(NoRedir).open(req, timeout=10); status, text, rh = r.status, r.read().decode(), dict(r.headers)
except urllib.error.HTTPError as e:
    status, text, rh = e.code, e.read().decode(), dict(e.headers)
def seen(container):
    out = subprocess.run(["docker", "logs", container], capture_output=True, text=True).stdout
    return [json.loads(l) for l in out.splitlines() if tid in l]
keep = lambda h: {k: v for k, v in h.items() if k.startswith(("X-", "Next-", "Authorization", "Rsc", "Sec-Fetch")) and k not in ("X-Test-Id",)}
print(f"== {method} :{port}{path}  -> {status} {rh.get('Location','')}")
for w in seen("aisc-t-spike-platform"):
    if w["path"].startswith("/authz/witness"):
        print("  witness saw:", w["method"], w["path"], json.dumps(keep(w["headers"])))
try:
    app = json.loads(text)
    print(f"  app {app['who']} got:", app["method"], app["path"], json.dumps(keep(app["headers"])), "body:", repr(app["body"][:60]))
except Exception:
    print("  body:", text[:120].replace("\n", " "))
