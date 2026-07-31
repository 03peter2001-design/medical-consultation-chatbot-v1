#!/usr/bin/env bash

set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd -- "${SCRIPT_DIR}/.." && pwd)"
BACKEND_DIR="${PROJECT_ROOT}/backend"
VENV_DIR="${BACKEND_DIR}/venv"
VENV_PYTHON="${VENV_DIR}/bin/python"

log() {
  printf '[%s] %s\n' "$1" "$2"
}

fail() {
  log "ERROR" "$1" >&2
  exit 1
}

python_is_supported() {
  "$1" -c 'import sys; raise SystemExit(sys.version_info < (3, 12))' \
    >/dev/null 2>&1
}

find_python() {
  local candidate

  if [[ -n "${PYTHON_BIN:-}" ]]; then
    command -v "${PYTHON_BIN}" >/dev/null 2>&1 ||
      fail "PYTHON_BIN does not point to an executable command: ${PYTHON_BIN}"
    python_is_supported "${PYTHON_BIN}" ||
      fail "PYTHON_BIN must use Python 3.12 or newer"
    printf '%s\n' "${PYTHON_BIN}"
    return
  fi

  for candidate in python3.12 python3; do
    if command -v "${candidate}" >/dev/null 2>&1 &&
      python_is_supported "${candidate}"; then
      command -v "${candidate}"
      return
    fi
  done

  fail "Python 3.12 or newer is required"
}

skip_backend=false
for argument in "$@"; do
  if [[ "${argument}" == "--skip-backend" ]]; then
    skip_backend=true
    break
  fi
done

SYSTEM_PYTHON="$(find_python)"
RUNNER_PYTHON="${SYSTEM_PYTHON}"

if [[ "${skip_backend}" == false ]]; then
  if [[ ! -x "${VENV_PYTHON}" ]]; then
    log "RUN" "Creating backend Python environment with ${SYSTEM_PYTHON}"
    "${SYSTEM_PYTHON}" -m venv "${VENV_DIR}"
  elif ! python_is_supported "${VENV_PYTHON}"; then
    fail "Existing backend/venv uses Python older than 3.12; recreate that environment"
  else
    log "SKIP" "backend/venv already exists and uses a supported Python"
  fi
  RUNNER_PYTHON="${VENV_PYTHON}"
else
  log "SKIP" "Python environment creation disabled by --skip-backend"
fi

exec "${RUNNER_PYTHON}" "${SCRIPT_DIR}/bootstrap.py" "$@"
