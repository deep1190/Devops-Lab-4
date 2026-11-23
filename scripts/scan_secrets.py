"""Secret scanner used as a CI gate: fails the build if credentials are committed.
Usage: python scripts/scan_secrets.py [--selftest]
"""
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PATTERNS = {
    "AWS access key": r"AKIA[0-9A-Z]{16}",
    "Private key": r"-----BEGIN (RSA |EC |OPENSSH )?PRIVATE KEY-----",
    "GitHub token": r"gh[pousr]_[A-Za-z0-9]{36,}",
    "Hard-coded password/token": r"(?i)(password|passwd|secret|api[_-]?token)\s*[:=]\s*['\"][A-Za-z0-9/+_\-]{8,}['\"]",
}
SKIP_DIRS = {".git", "__pycache__", ".pytest_cache", "evidence", "node_modules"}
SKIP_FILES = {"scan_secrets.py"}


def scan(root):
    hits = []
    for d, dirs, files in os.walk(root):
        dirs[:] = [x for x in dirs if x not in SKIP_DIRS]
        for fn in files:
            if fn in SKIP_FILES or fn.endswith((".pyc", ".db")):
                continue
            path = os.path.join(d, fn)
            try:
                text = open(path, errors="ignore").read()
            except OSError:
                continue
            for name, pat in PATTERNS.items():
                for m in re.finditer(pat, text):
                    hits.append((os.path.relpath(path, root), name))
    return hits


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        import tempfile
        t = tempfile.mkdtemp()
        open(os.path.join(t, "bad.py"), "w").write('API_TOKEN = "supersecretvalue123"\n')
        found = scan(t)
        print("selftest:", "scanner detects planted secret" if found else "SCANNER BROKEN")
        sys.exit(0 if found else 1)
    hits = scan(ROOT)
    for f, n in hits:
        print(f"LEAK: {n} in {f}")
    print("secret scan:", "FAILED" if hits else "clean, no hard-coded credentials found")
    sys.exit(1 if hits else 0)
