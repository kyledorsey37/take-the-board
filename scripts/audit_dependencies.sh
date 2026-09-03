#!/usr/bin/env bash

set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
if [[ -z "${PIP_AUDIT_BIN:-}" ]]; then
  for candidate in "${PROJECT_ROOT}/.security-venv/bin/pip-audit" "${PROJECT_ROOT}/.venv/bin/pip-audit"; do
    if [[ -x "${candidate}" ]]; then
      PIP_AUDIT_BIN="${candidate}"
      break
    fi
  done
fi
PIP_AUDIT_BIN="${PIP_AUDIT_BIN:-pip-audit}"

if [[ ! -f "${PROJECT_ROOT}/requirements.lock" ]]; then
  echo "requirements.lock is missing; regenerate it before auditing dependencies." >&2
  exit 1
fi

if ! command -v "${PIP_AUDIT_BIN}" >/dev/null 2>&1; then
  echo "pip-audit is required. Install the pinned security tools, then rerun this command." >&2
  exit 127
fi

exec "${PIP_AUDIT_BIN}" --requirement "${PROJECT_ROOT}/requirements.lock"
