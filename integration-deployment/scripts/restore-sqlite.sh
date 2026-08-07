#!/usr/bin/env sh
set -eu

if [ "$#" -ne 2 ] || [ "$2" != "--confirm-restore" ]; then
  echo "Usage: $0 <backup-file-name> --confirm-restore" >&2
  exit 2
fi

case "$1" in
  */*|*\\*) echo "Pass a file name from integration-deployment/backups, not a path." >&2; exit 2 ;;
esac

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
DEPLOY_DIR=$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd)
BACKUP_FILE="$DEPLOY_DIR/backups/$1"

if [ ! -s "$BACKUP_FILE" ]; then
  echo "Backup does not exist or is empty: $BACKUP_FILE" >&2
  exit 1
fi

cd "$DEPLOY_DIR"
"$SCRIPT_DIR/backup-sqlite.sh"
docker compose stop backend
docker compose run --rm --no-deps -e "RESTORE_PATH=/backups/$1" backend \
  python -c 'import os, sqlite3; from pathlib import Path; db="/var/lib/medical-consultation/consultations.db"; source=sqlite3.connect("file:" + os.environ["RESTORE_PATH"] + "?mode=ro", uri=True); assert source.execute("PRAGMA integrity_check").fetchone()[0] == "ok"; [Path(db + suffix).unlink(missing_ok=True) for suffix in ("-wal", "-shm")]; target=sqlite3.connect(db); source.backup(target); assert target.execute("PRAGMA integrity_check").fetchone()[0] == "ok"; target.close(); source.close()'
docker compose up -d backend
echo "Restored $1. Check docker compose ps and /v1/health before clinical use."
