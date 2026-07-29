#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd -- "${SCRIPT_DIR}/.." && pwd)"
SMART_APP_PORT="${SMART_APP_PORT:-5174}"
SMART_LAUNCHER_PORT="${SMART_LAUNCHER_PORT:-8090}"
FHIR_BASE_URL="http://127.0.0.1:8080/fhir"

cd "${PROJECT_DIR}"

echo "Checking existing HAPI FHIR at ${FHIR_BASE_URL} ..."
curl --fail --silent --show-error --max-time 10 \
  -H "Accept: application/fhir+json" \
  "${FHIR_BASE_URL}/metadata" >/dev/null

SMART_APP_PORT="${SMART_APP_PORT}" \
SMART_LAUNCHER_PORT="${SMART_LAUNCHER_PORT}" \
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

cat <<EOF
SMART on FHIR is ready.

Test entry:       http://127.0.0.1:${SMART_APP_PORT}/start.html
SMART Launcher:   http://127.0.0.1:${SMART_LAUNCHER_PORT}
SMART discovery:  ${SMART_DISCOVERY_URL}
Existing HAPI:    ${FHIR_BASE_URL}
EOF
