#!/usr/bin/env bash

set -euo pipefail

image="${1:?Image URI is required.}"
deployment_dir="${TTB_DEPLOYMENT_DIR:-/opt/ttb}"
environment_file="${deployment_dir}/.env"
asset_container="ttb-deploy-assets"

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

env -u TAKEBOARD_IMAGE -u TAKEBOARD_ENV_FILE \
  docker compose --env-file "${environment_file}" run --rm web python manage.py migrate --noinput

env -u TAKEBOARD_IMAGE -u TAKEBOARD_ENV_FILE \
  docker compose --env-file "${environment_file}" up -d --no-deps --force-recreate web caddy

if setting_enabled TAKEBOARD_DEMO_BIDDING_ENABLED || setting_enabled TAKEBOARD_STRIPE_ENABLED; then
  env -u TAKEBOARD_IMAGE -u TAKEBOARD_ENV_FILE \
    docker compose --env-file "${environment_file}" up -d --no-deps --force-recreate worker
else
  echo "Bid finalization is disabled; stopping the worker."
  env -u TAKEBOARD_IMAGE -u TAKEBOARD_ENV_FILE \
    docker compose --env-file "${environment_file}" stop worker >/dev/null || true
fi

docker image prune --force >/dev/null
env -u TAKEBOARD_IMAGE -u TAKEBOARD_ENV_FILE \
  docker compose --env-file "${environment_file}" ps
