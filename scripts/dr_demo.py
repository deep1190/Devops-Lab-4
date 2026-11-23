"""Disaster-recovery demo: backup -> disaster -> restore -> failover, with measured RTO/RPO.

Objectives (documented targets):  RTO <= 60 s   RPO <= 5 min (backup every 5 min)
Writes evidence/02-disaster-recovery.txt
"""
import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "evidence", "02-disaster-recovery.txt")
RTO_TARGET_S = 60
lines = []


def log(m):
    print(m)
    lines.append(m)


work = tempfile.mkdtemp()
primary_db, standby_db, backups = f"{work}/primary/notes.db", f"{work}/standby/notes.db", f"{work}/backups"


def start(port, db, color):
    env = dict(os.environ, PORT=str(port), DB_PATH=db, APP_COLOR=color, APP_VERSION="1.0.0")
    return subprocess.Popen([sys.executable, "-m", "gunicorn", "-b", f"127.0.0.1:{port}", "app:app"],
                            cwd=os.path.join(ROOT, "app"), env=env,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def wait_up(port):
    for _ in range(100):
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=1).read()
            return
        except Exception:
            time.sleep(0.1)
    raise SystemExit("app did not start")


def post(port, text):
    req = urllib.request.Request(f"http://127.0.0.1:{port}/notes", method="POST",
                                 data=json.dumps({"text": text}).encode(),
                                 headers={"Content-Type": "application/json"})
    urllib.request.urlopen(req).read()


def notes(port):
    return json.loads(urllib.request.urlopen(f"http://127.0.0.1:{port}/notes").read())


primary = start(5101, primary_db, "primary")
standby = None
try:
    wait_up(5101)
    log("== Disaster recovery demo ==")
    log(f"Objectives: RTO <= {RTO_TARGET_S}s, RPO <= 5 min (scheduled backup)")
    for i in range(1, 6):
        post(5101, f"note {i}")
    log("1) Primary running with 5 notes")

    out = subprocess.run([os.path.join(ROOT, "dr", "backup.sh"), primary_db, backups],
                         capture_output=True, text=True, check=True).stdout.strip()
    log(f"2) BACKUP: {out.replace(work, '<tmp>')}")

    post(5101, "note 6 (written AFTER the backup)")
    post(5101, "note 7 (written AFTER the backup)")
    log("3) Two more notes written after the backup (these are at risk)")

    t0 = time.time()
    primary.kill(); primary.wait()
    os.remove(primary_db)
    log("4) DISASTER: primary process killed and its database file destroyed")

    r = subprocess.run([os.path.join(ROOT, "dr", "restore.sh"), backups, standby_db],
                       capture_output=True, text=True, check=True).stdout.strip()
    log("5) RESTORE: " + r.replace(work, "<tmp>").replace("\n", " | "))
    standby = start(5102, standby_db, "standby")
    wait_up(5102)
    rto = time.time() - t0
    log("6) FAILOVER: standby started on :5102 from the restored backup")

    got = notes(5102)
    lost = 7 - len(got)
    log(f"   Notes recovered: {len(got)} of 7  ->  data lost (actual RPO impact): {lost} notes")
    log(f"   Measured RTO: {rto:.2f}s  (target {RTO_TARGET_S}s) -> {'MET' if rto <= RTO_TARGET_S else 'MISSED'}")
    log("   Corruption check: tampering with the backup must be rejected...")
    bk = sorted(os.listdir(backups))[0]
    with open(f"{backups}/{bk}", "ab") as f:
        f.write(b"x")
    bad = subprocess.run([os.path.join(ROOT, "dr", "restore.sh"), backups, f"{work}/x.db"], capture_output=True, text=True)
    log(f"   restore of tampered backup exit code = {bad.returncode} ({'rejected, good' if bad.returncode else 'ACCEPTED, bad'})")
    log("OBSERVATION: data written after the last backup is lost; shrink RPO with more frequent backups or replication.")
finally:
    for p in (primary, standby):
        if p:
            p.kill()
    with open(OUT, "w") as f:
        f.write("\n".join(lines) + "\n")
