#!/usr/bin/env sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
DEPLOY_DIR=$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd)
STAMP=$(date -u +%Y%m%dT%H%M%SZ)
BACKUP_NAME="consultations-$STAMP.sqlite3"
HOST_UID=$(id -u)
HOST_GID=$(id -g)

cd "$DEPLOY_DIR"
mkdir -p backups
docker compose exec -T -e "BACKUP_PATH=/backups/$BACKUP_NAME" \
  -e "HOST_UID=$HOST_UID" -e "HOST_GID=$HOST_GID" backend \
  python -c 'import os, sqlite3; path=os.environ["BACKUP_PATH"]; source=sqlite3.connect("/var/lib/medical-consultation/consultations.db"); assert source.execute("PRAGMA integrity_check").fetchone()[0] == "ok"; target=sqlite3.connect(path); source.backup(target); assert target.execute("PRAGMA integrity_check").fetchone()[0] == "ok"; target.close(); source.close(); os.chmod(path, 0o600); os.chown(path, int(os.environ["HOST_UID"]), int(os.environ["HOST_GID"]))'
echo "Created $DEPLOY_DIR/backups/$BACKUP_NAME"
