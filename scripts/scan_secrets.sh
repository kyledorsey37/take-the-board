#!/usr/bin/env bash

set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
GITLEAKS_BIN="${GITLEAKS_BIN:-gitleaks}"
GITLEAKS_DOCKER_IMAGE="${GITLEAKS_DOCKER_IMAGE:-}"

tracked_env_files="$(git -C "${PROJECT_ROOT}" ls-files -- '.env' '.env.*' '.resend-dev-key' ':!.env.example')"
if [[ -n "${tracked_env_files}" ]]; then
  echo "Refusing to scan with a tracked local secret file present; remove it from Git and rotate any credential first." >&2
  exit 1
fi

if [[ -n "${GITLEAKS_DOCKER_IMAGE}" ]]; then
  if ! command -v docker >/dev/null 2>&1; then
    echo "docker is required when GITLEAKS_DOCKER_IMAGE is set." >&2
    exit 127
  fi

  exec docker run --rm --network none \
    --volume "${PROJECT_ROOT}:/repo:ro" \
    --workdir /repo \
    "${GITLEAKS_DOCKER_IMAGE}" dir \
    --config /repo/.gitleaks.toml \
    --redact \
    --no-banner \
    --log-level error \
    --exit-code 1 \
    /repo
fi

if ! command -v "${GITLEAKS_BIN}" >/dev/null 2>&1; then
  echo "gitleaks is required. Install it from https://github.com/gitleaks/gitleaks, then rerun this command." >&2
  exit 127
fi

exec "${GITLEAKS_BIN}" dir \
  --config "${PROJECT_ROOT}/.gitleaks.toml" \
  --redact \
  --no-banner \
  --log-level error \
  --exit-code 1 \
  "${PROJECT_ROOT}"
