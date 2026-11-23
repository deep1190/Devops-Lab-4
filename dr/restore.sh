#!/usr/bin/env bash
# Verify checksum, then restore latest backup. Usage: ./restore.sh <backup_dir> <db_path>
set -euo pipefail
DIR="${1:?backup dir}"; DB="${2:?target db path}"
LATEST=$(ls -1t "$DIR"/notes-*.db | head -1)
sha256sum -c "$LATEST.sha256"          # refuse to restore a corrupted backup
mkdir -p "$(dirname "$DB")"
cp "$LATEST" "$DB"
python3 -c "import sqlite3,sys;c=sqlite3.connect(sys.argv[1]);print('integrity:',c.execute('PRAGMA integrity_check').fetchone()[0])" "$DB"
echo "restored $LATEST -> $DB"
