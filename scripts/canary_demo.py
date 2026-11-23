
"""Canary deployment demo with automatic rollback.

Run:
    python scripts/canary_demo.py bad
    python scripts/canary_demo.py good

Uses Waitress for Windows compatibility.
Writes evidence/04-canary-<mode>.txt
"""

import json
import os
import sys
import time
import subprocess
import urllib.request
import urllib.error

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APP_DIR = os.path.join(ROOT, "app")
ROUTER = "http://127.0.0.1:8080"

MODE = sys.argv[1].lower() if len(sys.argv) > 1 else "bad"

if MODE not in ("bad", "good"):
    raise SystemExit("Usage: python scripts/canary_demo.py [bad|good]")

OUT = os.path.join(ROOT, "evidence", f"04-canary-{MODE}.txt")

STEPS = [5, 25, 50, 100]
ERROR_RATE_LIMIT = 0.05
LATENCY_LIMIT_MS = 500
REQS_PER_STEP = 300

lines = []


def log(message):
    print(message, flush=True)
    lines.append(message)


def start_app(port, version, color, extra=None):
    env = dict(
        os.environ,
        APP_VERSION=version,
        APP_COLOR=color,
        PORT=str(port),
        DB_PATH=os.path.join(ROOT, f"canary_{color}.db"),
        **(extra or {})
    )

    return subprocess.Popen(
        [
            sys.executable,
            "-m",
            "waitress",
            f"--listen=127.0.0.1:{port}",
            "app:app"
        ],
        cwd=APP_DIR,
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL
    )


def call(path, method="GET", data=None):
    request = urllib.request.Request(
        ROUTER + path,
        method=method,
        data=json.dumps(data).encode() if data is not None else None,
        headers={"Content-Type": "application/json"}
    )

    try:
        with urllib.request.urlopen(request, timeout=3) as response:
            body = response.read()
            return response.status, json.loads(body) if body else None

    except urllib.error.HTTPError as error:
        return error.code, None

    except Exception:
        return 0, None


def wait_up(url, process=None):
    for _ in range(50):
        if process is not None and process.poll() is not None:
            raise RuntimeError(
                f"Process exited unexpectedly with code {process.returncode}: {url}"
            )

        try:
            with urllib.request.urlopen(url, timeout=1) as response:
                if response.status == 200:
                    return
        except Exception:
            time.sleep(0.2)

    raise RuntimeError(f"{url} never came up")


def snapshot():
    status, data = call("/_router/status")

    if status != 200 or not data or "stats" not in data:
        raise RuntimeError("Could not retrieve router statistics")

    return data["stats"]


def main():
    fail_rate = "0.30" if MODE == "bad" else "0"

    procs = []

    try:
        blue = start_app(5001, "1.0.0", "blue")
        procs.append(blue)

        green = start_app(
            5002,
            "2.0.0",
            "green",
            {"FAIL_RATE": fail_rate}
        )
        procs.append(green)

        router = subprocess.Popen(
            [
                sys.executable,
                os.path.join(ROOT, "scripts", "router.py"),
                "8080"
            ],
            cwd=ROOT,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )
        procs.append(router)

        wait_up("http://127.0.0.1:5001/health", blue)
        wait_up("http://127.0.0.1:5002/health", green)
        wait_up(ROUTER + "/_router/status", router)

        log(f"== Canary rollout ({MODE} release) ==")
        log(
            f"Rollback triggers: canary error rate > {ERROR_RATE_LIMIT:.0%} "
            f"OR avg latency > {LATENCY_LIMIT_MS} ms"
        )
        log(
            f"{'step':>5} {'canary%':>8} {'canary_reqs':>12} "
            f"{'canary_err%':>12} {'stable_err%':>12} "
            f"{'canary_ms':>10}  decision"
        )

        outcome = "?"

        for index, pct in enumerate(STEPS, start=1):
            status, _ = call(
                "/_router/weights",
                "POST",
                {"blue": 100 - pct, "green": pct}
            )

            if status not in (200, 201):
                raise RuntimeError("Could not update router traffic weights")

            before = snapshot()

            for _ in range(REQS_PER_STEP):
                call("/notes")

            after = snapshot()

            delta = {
                key: {
                    metric: after[key][metric] - before[key][metric]
                    for metric in after[key]
                }
                for key in after
            }

            canary = delta["green"]
            stable = delta["blue"]

            canary_requests = canary["requests"]
            stable_requests = stable["requests"]

            canary_errors = (
                canary["errors"] / canary_requests
                if canary_requests else 0
            )

            stable_errors = (
                stable["errors"] / stable_requests
                if stable_requests else 0
            )

            canary_latency = (
                canary["latency_ms_total"] / canary_requests
                if canary_requests else 0
            )

            bad = canary_requests > 0 and (
                canary_errors > ERROR_RATE_LIMIT
                or canary_latency > LATENCY_LIMIT_MS
            )

            decision = (
                "ROLLBACK" if bad
                else "PROMOTE" if pct == 100
                else "continue"
            )

            log(
                f"{index:>5} {pct:>7}% {canary_requests:>12} "
                f"{canary_errors:>11.1%} {stable_errors:>11.1%} "
                f"{canary_latency:>10.1f}  {decision}"
            )

            if bad:
                call(
                    "/_router/weights",
                    "POST",
                    {"blue": 100, "green": 0}
                )

                log(
                    f"TRIGGER FIRED at {pct}% -> traffic returned "
                    "to stable (100% blue)."
                )

                outcome = "ROLLED BACK"
                break

        else:
            outcome = "PROMOTED"

        log(f"OUTCOME: {outcome}")

    finally:
        for process in reversed(procs):
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()

        os.makedirs(os.path.dirname(OUT), exist_ok=True)

        with open(OUT, "w", encoding="utf-8") as file:
            file.write("\n".join(lines) + "\n")


if __name__ == "__main__":
    main()
