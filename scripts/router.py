"""Tiny switchable reverse proxy used to demo blue-green and canary locally
(no Docker/nginx needed). It does the same job as the nginx configs in
blue-green/ and canary/:  route each request to blue or green by weight.

Control API (on the same port):
  GET  /_router/status
  POST /_router/weights   {"blue": 100, "green": 0}
Traffic metrics per backend are kept in memory and exposed on /_router/status.
"""
import json
import random
import sys
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8080
BACKENDS = {"blue": "http://127.0.0.1:5001", "green": "http://127.0.0.1:5002"}
weights = {"blue": 100, "green": 0}
stats = {k: {"requests": 0, "errors": 0, "latency_ms_total": 0.0} for k in BACKENDS}
lock = threading.Lock()


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, body, headers=None):
        data = body if isinstance(body, bytes) else json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(data)

    def _pick(self):
        with lock:
            total = sum(weights.values())
            r = random.uniform(0, total)
            acc = 0
            for name, w in weights.items():
                acc += w
                if r <= acc and w > 0:
                    return name
        return "blue"

    def do_GET(self):
        if self.path == "/_router/status":
            with lock:
                return self._send(200, {"weights": weights, "stats": stats})
        self._proxy("GET")

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length) if length else None
        if self.path == "/_router/weights":
            new = json.loads(body)
            with lock:
                weights.update({k: int(v) for k, v in new.items()})
            return self._send(200, {"weights": weights})
        self._proxy("POST", body)

    def _proxy(self, method, body=None):
        name = self._pick()
        req = urllib.request.Request(
            BACKENDS[name] + self.path, data=body, method=method,
            headers={"Content-Type": self.headers.get("Content-Type", "application/json")},
        )
        start = time.time()
        code, data = 502, b'{"error":"bad gateway"}'
        try:
            with urllib.request.urlopen(req, timeout=3) as resp:
                code, data = resp.status, resp.read()
        except urllib.error.HTTPError as e:
            code, data = e.code, e.read()
        except Exception:
            pass
        ms = (time.time() - start) * 1000
        with lock:
            s = stats[name]
            s["requests"] += 1
            s["latency_ms_total"] += ms
            if code >= 500:
                s["errors"] += 1
        self._send(code, data, {"X-Served-By": name})


if __name__ == "__main__":
    ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
