#!/usr/bin/env bash

set -euo pipefail

image="${1:?Image URI is required.}"
deployment_dir="${TTB_DEPLOYMENT_DIR:-/opt/ttb}"
configured_application_env_file="${TTB_APPLICATION_ENV_FILE:-.env}"
asset_container="ttb-deploy-assets"

if [[ "${configured_application_env_file}" == /* ]]; then
  environment_file="${configured_application_env_file}"
elif [[ "${configured_application_env_file}" == .. || "${configured_application_env_file}" == ../* || "${configured_application_env_file}" == */../* || "${configured_application_env_file}" == */.. ]]; then
  echo "TTB_APPLICATION_ENV_FILE must stay within the deployment directory or use an absolute path." >&2
  exit 1
else
  environment_file="${deployment_dir}/${configured_application_env_file}"
fi

read_env_setting() {
  local setting="$1"
  local file="$2"
  local value

  value="$(sed -n -E "s/^${setting}=//p" "${file}" | tail -n 1)"
  value="${value#\"}"
  value="${value%\"}"
  printf '%s' "${value}"
}

postgres_env_path() {
  local configured_path

  configured_path="$(read_env_setting TAKEBOARD_POSTGRES_ENV_FILE "${environment_file}")"
  configured_path="${configured_path:-.postgres.env}"

  if [[ "${configured_path}" == /* ]]; then
    printf '%s' "${configured_path}"
  elif [[ "${configured_path}" == .. || "${configured_path}" == ../* || "${configured_path}" == */../* || "${configured_path}" == */.. ]]; then
    echo "TAKEBOARD_POSTGRES_ENV_FILE must stay within the deployment directory or use an absolute path." >&2
    exit 1
  else
    printf '%s/%s' "${deployment_dir}" "${configured_path}"
  fi
}

validate_postgres_env_file() {
  local file="$1"

  if ! awk '
    function nonempty(value) {
      gsub(/^[[:space:]]+|[[:space:]]+$/, "", value)
      return value != "" && value != "\"\"" && value != "\047\047"
    }
    /^[[:space:]]*$/ || /^[[:space:]]*#/ { next }
    !/^[A-Z_][A-Z0-9_]*=/ { invalid = 1; next }
    {
      key = $0
      sub(/=.*/, "", key)
      value = $0
      sub(/^[^=]*=/, "", value)
      if (key != "POSTGRES_DB" && key != "POSTGRES_USER" && key != "POSTGRES_PASSWORD") invalid = 1
      if (++seen[key] > 1 || !nonempty(value)) invalid = 1
    }
    END {
      if (invalid || seen["POSTGRES_DB"] != 1 || seen["POSTGRES_USER"] != 1 || seen["POSTGRES_PASSWORD"] != 1) exit 1
    }
  ' "${file}"; then
    echo "PostgreSQL environment file ${file} must contain exactly one non-empty POSTGRES_DB, POSTGRES_USER, and POSTGRES_PASSWORD setting." >&2
    return 1
  fi
}

extract_legacy_postgres_env() {
  local source_file="$1"
  local destination_file="$2"

  if ! awk '
    /^POSTGRES_DB=/       { if (db++) duplicate = 1; db_line = $0; next }
    /^POSTGRES_USER=/     { if (user++) duplicate = 1; user_line = $0; next }
    /^POSTGRES_PASSWORD=/ { if (password++) duplicate = 1; password_line = $0; next }
    END {
      if (duplicate || !db || !user || !password || db_line == "POSTGRES_DB=" || user_line == "POSTGRES_USER=" || password_line == "POSTGRES_PASSWORD=") exit 1
      print db_line
      print user_line
      print password_line
    }
  ' "${source_file}" > "${destination_file}"; then
    echo "${source_file} must contain non-empty POSTGRES_DB, POSTGRES_USER, and POSTGRES_PASSWORD settings to bootstrap ${postgres_environment_file}." >&2
    return 1
  fi
}

canonicalize_postgres_env() {
  local source_file="$1"
  local destination_file="$2"

  awk '
    /^POSTGRES_DB=/       { db_line = $0; next }
    /^POSTGRES_USER=/     { user_line = $0; next }
    /^POSTGRES_PASSWORD=/ { password_line = $0; next }
    END {
      print db_line
      print user_line
      print password_line
    }
  ' "${source_file}" > "${destination_file}"
}

migrate_postgres_environment() {
  local legacy_keys_present
  local legacy_file
  local canonical_file
  local cleaned_environment_file

  postgres_environment_file="$(postgres_env_path)"

  if [[ -f "${postgres_environment_file}" ]]; then
    if [[ ! -d "$(dirname "${postgres_environment_file}")" ]]; then
      echo "Directory for PostgreSQL environment file ${postgres_environment_file} does not exist." >&2
      return 1
    fi
    validate_postgres_env_file "${postgres_environment_file}"
    chmod 600 "${postgres_environment_file}"
  else
    if [[ ! -d "$(dirname "${postgres_environment_file}")" ]]; then
      echo "Directory for PostgreSQL environment file ${postgres_environment_file} does not exist." >&2
      return 1
    fi
    legacy_file="$(mktemp "${deployment_dir}/.postgres.env.migrate.XXXXXX")"
    trap 'rm -f "${legacy_file}" "${canonical_file:-}" "${cleaned_environment_file:-}"' RETURN
    extract_legacy_postgres_env "${environment_file}" "${legacy_file}"
    validate_postgres_env_file "${legacy_file}"
    chmod 600 "${legacy_file}"
    mv "${legacy_file}" "${postgres_environment_file}"
    trap - RETURN
    echo "Created the dedicated PostgreSQL environment file at ${postgres_environment_file}."
  fi

  legacy_keys_present="$(grep -Ec '^POSTGRES_(DB|USER|PASSWORD)=' "${environment_file}" || true)"
  if [[ "${legacy_keys_present}" -gt 0 ]]; then
    legacy_file="$(mktemp "${deployment_dir}/.postgres.env.compare.XXXXXX")"
    canonical_file="$(mktemp "${deployment_dir}/.postgres.env.canonical.XXXXXX")"
    trap 'rm -f "${legacy_file}" "${canonical_file:-}" "${cleaned_environment_file:-}"' RETURN
    extract_legacy_postgres_env "${environment_file}" "${legacy_file}"
    canonicalize_postgres_env "${postgres_environment_file}" "${canonical_file}"
    if ! cmp -s "${legacy_file}" "${canonical_file}"; then
      echo "POSTGRES_* values in ${environment_file} do not match ${postgres_environment_file}; refusing to change database credentials." >&2
      return 1
    fi

    cleaned_environment_file="$(mktemp "${environment_file}.split.XXXXXX")"
    sed -E '/^POSTGRES_(DB|USER|PASSWORD)=/d' "${environment_file}" > "${cleaned_environment_file}"
    chmod 600 "${cleaned_environment_file}"
    mv "${cleaned_environment_file}" "${environment_file}"
    trap - RETURN
    echo "Removed legacy PostgreSQL settings from ${environment_file}; the existing database volume and credentials were preserved."
  fi
}

setting_enabled() {
  local setting="$1"
  local value

  value="$(sed -n -E "s/^${setting}=//p" "${environment_file}" | tail -n 1)"
  value="$(printf '%s' "${value}" | tr '[:upper:]' '[:lower:]')"
  case "${value}" in
    1|true|yes|on) return 0 ;;
    *) return 1 ;;
  esac
}

if [[ ! -f "${environment_file}" ]]; then
  echo "Missing ${environment_file}. Bootstrap the host before deploying." >&2
  exit 1
fi

chmod 600 "${environment_file}"
migrate_postgres_environment

if [[ "${TTB_VALIDATE_DEPLOYMENT_ENV_ONLY:-0}" == "1" ]]; then
  echo "Deployment environment contract validated."
  exit 0
fi

cd "${deployment_dir}"

if grep -q '^TAKEBOARD_IMAGE=' "${environment_file}"; then
  sed -i "s|^TAKEBOARD_IMAGE=.*|TAKEBOARD_IMAGE=${image}|" "${environment_file}"
else
  printf '\nTAKEBOARD_IMAGE=%s\n' "${image}" >> "${environment_file}"
fi

docker rm -f "${asset_container}" >/dev/null 2>&1 || true
docker create --name "${asset_container}" "${image}" >/dev/null
trap 'docker rm -f "${asset_container}" >/dev/null 2>&1 || true' EXIT

docker cp "${asset_container}:/app/deploy/dev/docker-compose.yml" ./docker-compose.yml
docker cp "${asset_container}:/app/deploy/dev/Caddyfile" ./Caddyfile
docker cp "${asset_container}:/app/staticfiles/." ./staticfiles/

env -u TAKEBOARD_IMAGE -u TAKEBOARD_ENV_FILE -u TAKEBOARD_POSTGRES_ENV_FILE \
  docker compose --env-file "${environment_file}" run --rm web python manage.py migrate --noinput

env -u TAKEBOARD_IMAGE -u TAKEBOARD_ENV_FILE -u TAKEBOARD_POSTGRES_ENV_FILE \
  docker compose --env-file "${environment_file}" up -d --no-deps --force-recreate web caddy

if setting_enabled TAKEBOARD_DEMO_BIDDING_ENABLED || setting_enabled TAKEBOARD_STRIPE_ENABLED; then
  env -u TAKEBOARD_IMAGE -u TAKEBOARD_ENV_FILE -u TAKEBOARD_POSTGRES_ENV_FILE \
    docker compose --env-file "${environment_file}" up -d --no-deps --force-recreate worker
else
  echo "Bid finalization is disabled; stopping the worker."
  env -u TAKEBOARD_IMAGE -u TAKEBOARD_ENV_FILE -u TAKEBOARD_POSTGRES_ENV_FILE \
    docker compose --env-file "${environment_file}" stop worker >/dev/null || true
fi

docker image prune --force >/dev/null
env -u TAKEBOARD_IMAGE -u TAKEBOARD_ENV_FILE -u TAKEBOARD_POSTGRES_ENV_FILE \
  docker compose --env-file "${environment_file}" ps
