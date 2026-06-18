#!/bin/sh
# Nightly consistent SQLite backup of the One Anthem DB.
# Cron (on the VPS):  0 2 * * *  cd /opt/allgud/arvisx/deploy && ./backup.sh >> backup.log 2>&1
set -e

COMPOSE="docker compose -f docker-compose.pilot.yml"
OUT="${BACKUP_DIR:-./backups}"
STAMP="$(date +%Y%m%d_%H%M%S)"
mkdir -p "$OUT"

# sqlite .backup = a consistent online snapshot (safe while the API is writing).
$COMPOSE exec -T api python -c \
  "import sqlite3,os; s=sqlite3.connect(os.environ['ARVISX_DB']); d=sqlite3.connect('/data/_bak.db'); s.backup(d); d.close(); s.close()"
$COMPOSE cp api:/data/_bak.db "$OUT/arvisx_$STAMP.db"
$COMPOSE exec -T api rm -f /data/_bak.db

# Retain the last 14 snapshots.
ls -1t "$OUT"/arvisx_*.db 2>/dev/null | tail -n +15 | xargs -r rm -f
echo "backup -> $OUT/arvisx_$STAMP.db"
