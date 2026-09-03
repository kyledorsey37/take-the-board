#!/usr/bin/env bash

set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
GITLEAKS_BIN="${GITLEAKS_BIN:-gitleaks}"

if ! command -v "${GITLEAKS_BIN}" >/dev/null 2>&1; then
  echo "gitleaks is required. Install it from https://github.com/gitleaks/gitleaks, then rerun this command." >&2
  exit 127
fi

tracked_env_files="$(git -C "${PROJECT_ROOT}" ls-files -- '.env' '.env.*' '.resend-dev-key' ':!.env.example')"
if [[ -n "${tracked_env_files}" ]]; then
  echo "Refusing to scan with a tracked local secret file present; remove it from Git and rotate any credential first." >&2
  exit 1
fi

exec "${GITLEAKS_BIN}" dir \
  --config "${PROJECT_ROOT}/.gitleaks.toml" \
  --redact \
  --no-banner \
  --log-level error \
  --exit-code 1 \
  "${PROJECT_ROOT}"
