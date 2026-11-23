"""Blue-green demo: switch 100% of traffic blue -> green while a client hammers
the router. Proves zero failed requests during the cutover, then rolls back.
Usage: python scripts/bluegreen_demo.py   (writes evidence/03-bluegreen.txt)
"""
import json
import os
import subprocess
import sys
import threading
import time
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ROUTER = "http://127.0.0.1:8080"
OUT = os.path.join(ROOT, "evidence", "03-bluegreen.txt")
lines = []


def log(msg):
    print(msg)
    lines.append(msg)


def start_app(port, version, color, extra=None):
    env = dict(os.environ, APP_VERSION=version, APP_COLOR=color, PORT=str(port),
               DB_PATH=f"/tmp/bg_{color}.db", **(extra or {}))
    return subprocess.Popen(
        [sys.executable, "-m", "gunicorn", "-b", f"127.0.0.1:{port}", "app:app"],
        cwd=os.path.join(ROOT, "app"), env=env,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def get(path):
    try:
        with urllib.request.urlopen(ROUTER + path, timeout=3) as r:
            return r.status, r.headers.get("X-Served-By"), json.loads(r.read())
    except Exception:
        return 0, None, None


def set_weights(blue, green):
    req = urllib.request.Request(ROUTER + "/_router/weights", method="POST",
                                 data=json.dumps({"blue": blue, "green": green}).encode(),
                                 headers={"Content-Type": "application/json"})
    urllib.request.urlopen(req).read()


def wait_up(url):
    for _ in range(50):
        try:
            urllib.request.urlopen(url, timeout=1).read()
            return
        except Exception:
            time.sleep(0.2)
    raise SystemExit(f"{url} never came up")


procs = [start_app(5001, "1.0.0", "blue"), start_app(5002, "2.0.0", "green"),
         subprocess.Popen([sys.executable, os.path.join(ROOT, "scripts", "router.py"), "8080"])]
try:
    for u in ("http://127.0.0.1:5001/health", "http://127.0.0.1:5002/health", ROUTER + "/_router/status"):
        wait_up(u)

    log("== Blue-Green zero-downtime switch ==")
    log("Live (blue) = v1.0.0 ; Idle (green) = v2.0.0 already deployed and health-checked")
    set_weights(100, 0)

    results, stop = [], threading.Event()

    def client():
        while not stop.is_set():
            code, who, body = get("/version")
            results.append((time.time(), code, who, body and body["version"]))
            time.sleep(0.01)

    t = threading.Thread(target=client)
    t.start()
    time.sleep(1.5)
    t_switch = time.time()
    set_weights(0, 100)           # <-- the cutover
    log(f"CUTOVER at t+{t_switch - results[0][0]:.2f}s: traffic 100% blue -> 100% green")
    time.sleep(1.5)
    t_rb = time.time()
    set_weights(100, 0)           # <-- instant rollback
    log(f"ROLLBACK at t+{t_rb - results[0][0]:.2f}s: traffic back to blue")
    time.sleep(1.0)
    stop.set(); t.join()

    total = len(results)
    failed = sum(1 for r in results if r[1] != 200)
    before = {r[3] for r in results if r[0] < t_switch}
    during = {r[3] for r in results if t_switch <= r[0] < t_rb}
    after = {r[3] for r in results if r[0] >= t_rb}
    log(f"Total requests during test : {total}")
    log(f"Failed requests            : {failed}")
    log(f"Versions seen before switch: {sorted(before)}")
    log(f"Versions seen after switch : {sorted(during)}")
    log(f"Versions seen after rollback: {sorted(after)}")
    log("RESULT: " + ("ZERO-DOWNTIME CONFIRMED" if failed == 0 else "DOWNTIME DETECTED"))
finally:
    for p in procs:
        p.terminate()
    with open(OUT, "w") as f:
        f.write("\n".join(lines) + "\n")
