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

# Read only the browser build settings we need. Do not source the deployment
# file: it also contains server credentials and is not required to be shell
# syntax. Values are never printed by this script.
read_deployment_setting() {
  setting_name=$1
  awk -v key="$setting_name" '
    index($0, key "=") == 1 {
      value = substr($0, length(key) + 2)
      sub(/\r$/, "", value)
      print value
    }
  ' "$DEPLOY_DIR/.env" | tail -n 1
}

avatar_provider_value=$(read_deployment_setting AVATAR_PROVIDER)
avatar_provider_value=${avatar_provider_value:-local}
did_client_key_value=$(read_deployment_setting DID_CLIENT_KEY)
did_agent_id_value=$(read_deployment_setting DID_AGENT_ID)

avatar_csp_connect_src_suffix=
case "$avatar_provider_value" in
  local) ;;
  did)
    if [ -z "$did_client_key_value" ] || [ -z "$did_agent_id_value" ]; then
      echo "DID_CLIENT_KEY and DID_AGENT_ID are required when AVATAR_PROVIDER=did." >&2
      exit 1
    fi
    avatar_csp_connect_src_suffix=' https://*.d-id.com wss://*.d-id.com'
    ;;
  *)
    echo "AVATAR_PROVIDER must be either local or did." >&2
    exit 1
    ;;
esac

export VITE_AVATAR_PROVIDER="$avatar_provider_value"
export VITE_DID_CLIENT_KEY="$did_client_key_value"
export VITE_DID_AGENT_ID="$did_agent_id_value"
export AVATAR_CSP_CONNECT_SRC_SUFFIX="$avatar_csp_connect_src_suffix"

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
