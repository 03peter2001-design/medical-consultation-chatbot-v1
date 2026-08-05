#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd -- "${SCRIPT_DIR}/.." && pwd)"
SMART_APP_PORT="${SMART_APP_PORT:-5174}"
SMART_LAUNCHER_PORT="${SMART_LAUNCHER_PORT:-8090}"
FHIR_BASE_URL="http://127.0.0.1:8080/fhir"
RAG_HF_HUB_CACHE="${RAG_HF_HUB_CACHE:-${HOME}/.cache/huggingface/hub}"
RAG_EMBEDDING_MODEL_DIR="${RAG_HF_HUB_CACHE}/models--sentence-transformers--paraphrase-multilingual-MiniLM-L12-v2"

cd "${PROJECT_DIR}"

echo "Checking existing HAPI FHIR at ${FHIR_BASE_URL} ..."
curl --fail --silent --show-error --max-time 10 \
  -H "Accept: application/fhir+json" \
  "${FHIR_BASE_URL}/metadata" >/dev/null

if [[ ! -f backend/.env ]]; then
  echo "Missing backend/.env. Run ./scripts/bootstrap.sh or copy backend/.env.example first." >&2
  exit 1
fi

if [[ ! -f backend/chroma_db/chroma.sqlite3 ]]; then
  echo "Missing backend/chroma_db. Run ./scripts/bootstrap.sh --with-rag first." >&2
  exit 1
fi

mkdir -p "${RAG_HF_HUB_CACHE}"

if [[ ! -f "${RAG_EMBEDDING_MODEL_DIR}/refs/main" ]]; then
  echo "Missing cached RAG embedding model. Run ./scripts/bootstrap.sh --with-rag first." >&2
  exit 1
fi

SMART_APP_PORT="${SMART_APP_PORT}" \
SMART_LAUNCHER_PORT="${SMART_LAUNCHER_PORT}" \
RAG_HF_HUB_CACHE="${RAG_HF_HUB_CACHE}" \
docker compose \
  -f compose.smart.yml \
  up -d --build --remove-orphans

SMART_DISCOVERY_URL="http://127.0.0.1:${SMART_LAUNCHER_PORT}/v/r4/fhir/.well-known/smart-configuration"
echo "Waiting for SMART discovery at ${SMART_DISCOVERY_URL} ..."
for _ in $(seq 1 30); do
  if curl --fail --silent --max-time 3 "${SMART_DISCOVERY_URL}" >/dev/null; then
    break
  fi
  sleep 1
done

BACKEND_HEALTH_URL="http://127.0.0.1:${SMART_APP_PORT}/api/v1/health"
echo "Checking RAG status at ${BACKEND_HEALTH_URL} ..."
HEALTH_PAYLOAD=""
for _ in $(seq 1 30); do
  if HEALTH_PAYLOAD="$(
    curl --fail --silent --max-time 3 "${BACKEND_HEALTH_URL}"
  )"; then
    break
  fi
  sleep 1
done

if [[ -z "${HEALTH_PAYLOAD}" ]]; then
  echo "Backend health endpoint did not become ready: ${BACKEND_HEALTH_URL}" >&2
  exit 1
fi

RAG_STATUS="$(
  python3 -c '
import json
import sys

health = json.load(sys.stdin)
if not health.get("rag_enabled"):
    raise SystemExit(
        "RAG disabled: "
        + json.dumps(
            {
                "version": health.get("rag_index_version"),
                "collections": health.get("rag_collections"),
            },
            ensure_ascii=False,
        )
    )
print(
    f"enabled ({health.get('"'"'rag_index_version'"'"')}: "
    f"{'"'"', '"'"'.join(health.get('"'"'rag_collections'"'"') or [])})"
)
' <<<"${HEALTH_PAYLOAD}"
)"

cat <<EOF
SMART on FHIR is ready.

Test entry:       http://127.0.0.1:${SMART_APP_PORT}/start.html
SMART Launcher:   http://127.0.0.1:${SMART_LAUNCHER_PORT}
SMART discovery:  ${SMART_DISCOVERY_URL}
Existing HAPI:    ${FHIR_BASE_URL}
Backend health:   ${BACKEND_HEALTH_URL}
RAG:              ${RAG_STATUS}
EOF
