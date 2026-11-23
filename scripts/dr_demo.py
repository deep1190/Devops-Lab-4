
"""Disaster-recovery demo: backup -> disaster -> restore -> failover.

Objectives: RTO <= 60 seconds; backup-based recovery.
Writes evidence/02-disaster-recovery.txt
"""

import os
import sys
import json
import time
import glob
import hashlib
import sqlite3
import tempfile
import subprocess
import urllib.request
import urllib.error

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APP_DIR = os.path.join(ROOT, "app")
OUT = os.path.join(ROOT, "evidence", "02-disaster-recovery.txt")

RTO_TARGET_S = 60
lines = []


def log(message):
    print(message, flush=True)
    lines.append(message)


def create_backup(db_path, backup_dir):
    os.makedirs(backup_dir, exist_ok=True)

    stamp = time.strftime("%Y%m%d-%H%M%S")
    backup_file = os.path.join(backup_dir, f"notes-{stamp}.db")

    source = sqlite3.connect(db_path)
    destination = sqlite3.connect(backup_file)

    try:
        source.backup(destination)
    finally:
        destination.close()
        source.close()

    with open(backup_file, "rb") as file:
        checksum = hashlib.sha256(file.read()).hexdigest()

    with open(backup_file + ".sha256", "w") as file:
        file.write(checksum)

    return backup_file


def restore_backup(backup_dir, db_path):
    backups = glob.glob(os.path.join(backup_dir, "notes-*.db"))

    if not backups:
        raise FileNotFoundError("No backup files found")

    latest = max(backups, key=os.path.getmtime)
    checksum_file = latest + ".sha256"

    if not os.path.exists(checksum_file):
        raise ValueError("Backup checksum file is missing")

    with open(checksum_file, "r") as file:
        expected = file.read().strip()

    with open(latest, "rb") as file:
        actual = hashlib.sha256(file.read()).hexdigest()

    if actual != expected:
        raise ValueError("Backup checksum verification failed")

    os.makedirs(os.path.dirname(db_path), exist_ok=True)

    source = sqlite3.connect(latest)
    destination = sqlite3.connect(db_path)

    try:
        source.backup(destination)
    finally:
        destination.close()
        source.close()

    return latest


def start(port, db_path, color):
    env = dict(
        os.environ,
        PORT=str(port),
        DB_PATH=db_path,
        APP_COLOR=color,
        APP_VERSION="1.0.0"
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


def wait_up(port, process):
    for _ in range(100):
        if process.poll() is not None:
            raise RuntimeError(
                f"Application on port {port} exited with code "
                f"{process.returncode}"
            )

        try:
            with urllib.request.urlopen(
                f"http://127.0.0.1:{port}/health",
                timeout=1
            ) as response:
                if response.status == 200:
                    return
        except Exception:
            time.sleep(0.1)

    raise RuntimeError(f"Application on port {port} did not start")


def post(port, text):
    request = urllib.request.Request(
        f"http://127.0.0.1:{port}/notes",
        method="POST",
        data=json.dumps({"text": text}).encode(),
        headers={"Content-Type": "application/json"}
    )

    with urllib.request.urlopen(request, timeout=5) as response:
        response.read()


def notes(port):
    with urllib.request.urlopen(
        f"http://127.0.0.1:{port}/notes",
        timeout=5
    ) as response:
        return json.loads(response.read())


def main():
    work = tempfile.mkdtemp(prefix="dr_demo_")

    primary_db = os.path.join(work, "primary", "notes.db")
    standby_db = os.path.join(work, "standby", "notes.db")
    backups_dir = os.path.join(work, "backups")

    os.makedirs(os.path.dirname(primary_db), exist_ok=True)

    primary = None
    standby = None

    try:
        primary = start(5101, primary_db, "primary")
        wait_up(5101, primary)

        log("== Disaster recovery demo ==")
        log(f"Objectives: RTO <= {RTO_TARGET_S}s, RPO <= 5 min")

        for i in range(1, 6):
            post(5101, f"note {i}")

        log("1) Primary running with 5 notes")

        backup_file = create_backup(primary_db, backups_dir)
        log(
            "2) BACKUP: "
            + backup_file.replace(work, "<tmp>")
        )

        post(5101, "note 6 (written AFTER the backup)")
        post(5101, "note 7 (written AFTER the backup)")

        log("3) Two more notes written after the backup (these are at risk)")

        t0 = time.time()

        primary.kill()
        primary.wait(timeout=5)
        primary = None

        if os.path.exists(primary_db):
            os.remove(primary_db)

        log("4) DISASTER: primary process killed and database destroyed")

        restored_file = restore_backup(backups_dir, standby_db)

        log(
            "5) RESTORE: restored from "
            + os.path.basename(restored_file)
        )

        standby = start(5102, standby_db, "standby")
        wait_up(5102, standby)

        rto = time.time() - t0

        log("6) FAILOVER: standby started on port 5102")

        recovered_notes = notes(5102)
        recovered_count = len(recovered_notes)
        lost = 7 - recovered_count

        log(
            f"   Notes recovered: {recovered_count} of 7 "
            f"-> data lost: {lost} notes"
        )

        log(
            f"   Measured RTO: {rto:.2f}s "
            f"(target {RTO_TARGET_S}s) -> "
            f"{'MET' if rto <= RTO_TARGET_S else 'MISSED'}"
        )

        log("7) Corruption check: tampering with backup...")

        backup_files = glob.glob(
            os.path.join(backups_dir, "notes-*.db")
        )
        latest = max(backup_files, key=os.path.getmtime)

        with open(latest, "ab") as file:
            file.write(b"x")

        try:
            restore_backup(
                backups_dir,
                os.path.join(work, "corrupted_restore", "notes.db")
            )
            rejected = False
        except ValueError:
            rejected = True

        log(
            "   Tampered backup: "
            + ("REJECTED, GOOD" if rejected else "ACCEPTED, BAD")
        )

        log(
            "OBSERVATION: Data written after the last backup is lost. "
            "More frequent backups or replication can reduce data loss."
        )

    finally:
        for process in (primary, standby):
            if process and process.poll() is None:
                process.kill()
                process.wait()

        os.makedirs(os.path.dirname(OUT), exist_ok=True)

        with open(OUT, "w", encoding="utf-8") as file:
            file.write("\n".join(lines) + "\n")


if __name__ == "__main__":
    main()
