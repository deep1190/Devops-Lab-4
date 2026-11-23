#!/usr/bin/env bash
# Consistent backup of the SQLite DB + integrity checksum. Usage: ./backup.sh <db_path> <backup_dir>
set -euo pipefail
DB="${1:?db path}"; DEST="${2:?backup dir}"
mkdir -p "$DEST"
STAMP=$(date +%Y%m%d-%H%M%S)
FILE="$DEST/notes-$STAMP.db"
python3 - "$DB" "$FILE" <<'PY'
import sqlite3, sys
src, dst = sqlite3.connect(sys.argv[1]), sqlite3.connect(sys.argv[2])
src.backup(dst)          # online, consistent copy (safe while app is running)
dst.close(); src.close()
PY
sha256sum "$FILE" > "$FILE.sha256"
echo "backup ok: $FILE"
