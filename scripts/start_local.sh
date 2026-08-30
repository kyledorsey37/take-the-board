#!/usr/bin/env bash

set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV_DIR="${PROJECT_ROOT}/.venv"
VENV_PYTHON="${VENV_DIR}/bin/python"

cd "${PROJECT_ROOT}"

# Use the same ignored local environment file that Docker Compose uses. This
# keeps LAN testing on the Mac's configured Cognito/Stripe path instead of
# silently falling back to the preview/free-play defaults.
if [[ -f "${PROJECT_ROOT}/.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "${PROJECT_ROOT}/.env"
  set +a
fi

# Docker Compose exposes the shared development Postgres on the host at 5433,
# while the web container reaches the same database at postgres:5432. If the
# ignored .env was copied from the container setup, normalize that hostname for
# this host process. An explicit LOCAL_DATABASE_URL remains available for a
# deliberate alternative.
if [[ -n "${LOCAL_DATABASE_URL:-}" ]]; then
  export DATABASE_URL="${LOCAL_DATABASE_URL}"
elif [[ -z "${DATABASE_URL:-}" || "${DATABASE_URL}" == *"@postgres:"* ]]; then
  export DATABASE_URL="postgres://takeboard:takeboard@127.0.0.1:${POSTGRES_PORT:-5433}/takeboard"
fi

if [[ ! -x "${VENV_PYTHON}" ]]; then
  PYTHON_BIN="${PYTHON_BIN:-}"
  if [[ -z "${PYTHON_BIN}" ]] && command -v python3.12 >/dev/null 2>&1; then
    PYTHON_BIN="$(command -v python3.12)"
  fi
  if [[ -z "${PYTHON_BIN}" ]] && [[ -x /opt/homebrew/bin/python3.12 ]]; then
    PYTHON_BIN="/opt/homebrew/bin/python3.12"
  fi
  if [[ -z "${PYTHON_BIN}" ]]; then
    echo "Python 3.12 is required. Install it or set PYTHON_BIN=/path/to/python3.12." >&2
    exit 1
  fi

  echo "Creating ${VENV_DIR} with ${PYTHON_BIN}..."
  "${PYTHON_BIN}" -m venv "${VENV_DIR}"
fi

if ! "${VENV_PYTHON}" -c "import django, unfold" >/dev/null 2>&1; then
  echo "Installing local Python dependencies..."
  "${VENV_PYTHON}" -m pip install -r requirements.txt
fi

export DJANGO_SETTINGS_MODULE="${DJANGO_SETTINGS_MODULE:-config.settings.local}"
export DJANGO_DEBUG="${DJANGO_DEBUG:-true}"
export DJANGO_SECRET_KEY="${DJANGO_SECRET_KEY:-unsafe-local-dev-key-change-me}"
export DJANGO_ALLOWED_HOSTS="${DJANGO_ALLOWED_HOSTS:-*}"

"${VENV_PYTHON}" manage.py migrate --noinput

if [[ "${SKIP_SEED_DEMO_DATA:-0}" != "1" ]]; then
  "${VENV_PYTHON}" manage.py seed_demo_data
fi

SERVER_ADDRESS="${DJANGO_BIND_ADDRESS:-0.0.0.0:8000}"
SERVER_PORT="${SERVER_ADDRESS##*:}"
if command -v lsof >/dev/null 2>&1 && lsof -nP -iTCP:"${SERVER_PORT}" -sTCP:LISTEN >/dev/null 2>&1; then
  echo "Port ${SERVER_PORT} is already in use. Stop the existing server or set DJANGO_BIND_ADDRESS=0.0.0.0:<port>." >&2
  exit 1
fi

echo "Starting Take the Board on ${SERVER_ADDRESS} (bound to ${SERVER_ADDRESS%%:*})"
exec "${VENV_PYTHON}" manage.py runserver "${SERVER_ADDRESS}" --insecure "$@"
