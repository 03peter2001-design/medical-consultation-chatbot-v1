#!/usr/bin/env sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
DEPLOY_DIR=$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd)
REPO_DIR=$(CDPATH= cd -- "$DEPLOY_DIR/.." && pwd)

for required in "$DEPLOY_DIR/.env" \
  "$DEPLOY_DIR/secrets/ucc-jwt-public.pem" \
  "$DEPLOY_DIR/secrets/tls-fullchain.pem" \
  "$DEPLOY_DIR/secrets/tls-private-key.pem"; do
  if [ ! -s "$required" ]; then
    echo "Missing required deployment file: $required" >&2
    exit 1
  fi
done

if grep -Eq 'example\.invalid|(^|=)replace-me($|[[:space:]])' "$DEPLOY_DIR/.env"; then
  echo "Replace all example host names and credentials in $DEPLOY_DIR/.env" >&2
  exit 1
fi
if grep -Eq '^UCC_API_BIND_IP=(0\.0\.0\.0|127\.0\.0\.1)$' "$DEPLOY_DIR/.env"; then
  echo "UCC_API_BIND_IP must be the Ubuntu private/LAN address." >&2
  exit 1
fi

for asset_dir in "$(sed -n 's/^RAG_CHROMA_DB_PATH=//p' "$DEPLOY_DIR/.env")" \
  "$(sed -n 's/^SNOMED_DATA_PATH=//p' "$DEPLOY_DIR/.env")" \
  "$(sed -n 's/^HF_MODEL_CACHE_PATH=//p' "$DEPLOY_DIR/.env")"; do
  [ -n "$asset_dir" ] || continue
  case "$asset_dir" in
    /*) resolved_asset_dir=$asset_dir ;;
    *) resolved_asset_dir="$DEPLOY_DIR/$asset_dir" ;;
  esac
  mkdir -p "$resolved_asset_dir"
done

cd "$REPO_DIR/frontend-v2"
if [ "${1:-}" != "--skip-install" ]; then
  npm ci
fi
npm run build:patient

cd "$DEPLOY_DIR"
docker compose config --quiet
docker compose up -d --build --remove-orphans
docker compose ps

echo "Patient gateway deployed. Verify the configured patient HTTPS /healthz endpoint."
