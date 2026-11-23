"""Canary demo with automatic rollback.
Stable (blue) v1.0.0 is healthy. Canary (green) v2.0.0 is deliberately faulty
(FAIL_RATE) so the controller must detect it and roll back.
Run with:  python scripts/canary_demo.py good   -> healthy canary, promoted to 100%
           python scripts/canary_demo.py bad    -> faulty canary, auto rollback
Writes evidence/04-canary-<mode>.txt
"""
import json
import os
import subprocess
import sys
import time
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ROUTER = "http://127.0.0.1:8080"
MODE = sys.argv[1] if len(sys.argv) > 1 else "bad"
OUT = os.path.join(ROOT, "evidence", f"04-canary-{MODE}.txt")

STEPS = [5, 25, 50, 100]          # % of traffic to canary
ERROR_RATE_LIMIT = 0.05            # rollback trigger: >5% 5xx on canary
LATENCY_LIMIT_MS = 500             # rollback trigger: avg latency
REQS_PER_STEP = 300
lines = []


def log(m):
    print(m)
    lines.append(m)


def start_app(port, version, color, extra=None):
    env = dict(os.environ, APP_VERSION=version, APP_COLOR=color, PORT=str(port),
               DB_PATH=f"/tmp/canary_{color}.db", **(extra or {}))
    return subprocess.Popen([sys.executable, "-m", "gunicorn", "-b", f"127.0.0.1:{port}", "app:app"],
                            cwd=os.path.join(ROOT, "app"), env=env,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def call(path, method="GET", data=None):
    req = urllib.request.Request(ROUTER + path, method=method,
                                 data=json.dumps(data).encode() if data else None,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=3) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, None
    except Exception:
        return 0, None


def wait_up(url):
    for _ in range(50):
        try:
            urllib.request.urlopen(url, timeout=1).read()
            return
        except Exception:
            time.sleep(0.2)
    raise SystemExit(f"{url} never came up")


def snapshot():
    return call("/_router/status")[1]["stats"]


fail_rate = "0.30" if MODE == "bad" else "0"
procs = [start_app(5001, "1.0.0", "blue"),
         start_app(5002, "2.0.0", "green", {"FAIL_RATE": fail_rate}),
         subprocess.Popen([sys.executable, os.path.join(ROOT, "scripts", "router.py"), "8080"])]
outcome = "?"
try:
    for u in ("http://127.0.0.1:5001/health", "http://127.0.0.1:5002/health", ROUTER + "/_router/status"):
        wait_up(u)
    log(f"== Canary rollout ({MODE} release) ==")
    log(f"Rollback triggers: canary error rate > {ERROR_RATE_LIMIT:.0%} OR avg latency > {LATENCY_LIMIT_MS} ms")
    log(f"{'step':>5} {'canary%':>8} {'canary_reqs':>12} {'canary_err%':>12} {'stable_err%':>12} {'canary_ms':>10}  decision")

    for pct in STEPS:
        call("/_router/weights", "POST", {"blue": 100 - pct, "green": pct})
        before = snapshot()
        for _ in range(REQS_PER_STEP):
            call("/notes")
        after = snapshot()
        d = {k: {m: after[k][m] - before[k][m] for m in after[k]} for k in after}
        c, s = d["green"], d["blue"]
        c_err = c["errors"] / c["requests"] if c["requests"] else 0
        s_err = s["errors"] / s["requests"] if s["requests"] else 0
        c_ms = c["latency_ms_total"] / c["requests"] if c["requests"] else 0
        bad = c["requests"] > 0 and (c_err > ERROR_RATE_LIMIT or c_ms > LATENCY_LIMIT_MS)
        decision = "ROLLBACK" if bad else ("PROMOTE" if pct == 100 else "continue")
        log(f"{STEPS.index(pct)+1:>5} {pct:>7}% {c['requests']:>12} {c_err:>11.1%} {s_err:>11.1%} {c_ms:>10.1f}  {decision}")
        if bad:
            call("/_router/weights", "POST", {"blue": 100, "green": 0})
            log(f"TRIGGER FIRED at {pct}% -> traffic returned to stable (100% blue). Blast radius: ~{pct}% of users for one step.")
            outcome = "ROLLED BACK"
            break
    else:
        outcome = "PROMOTED"
    log(f"OUTCOME: {outcome}")
finally:
    for p in procs:
        p.terminate()
    with open(OUT, "w") as f:
        f.write("\n".join(lines) + "\n")
