#!/usr/bin/env bash

set -euo pipefail

aws_profile="${TTB_AWS_PROFILE:-ttb-dev}"
aws_region="${TTB_AWS_REGION:-us-east-1}"
ecr_repository="${TTB_ECR_REPOSITORY:-ttb-dev}"
instance_name="${TTB_DEV_INSTANCE_NAME:-ttb-dev-ec2}"
instance_id="${TTB_DEV_INSTANCE_ID:-}"
local_env_file="${TTB_LOCAL_ENV_FILE:-.env}"

read_local_setting() {
  local setting="$1"
  local value="${!setting:-}"

  if [[ -z "${value}" && -f "${local_env_file}" ]]; then
    value="$(sed -n -E "s/^${setting}=//p" "${local_env_file}" | tail -n 1)"
  fi
  printf '%s' "${value}"
}

bedrock_enabled="$(read_local_setting TAKEBOARD_BEDROCK_ENABLED)"
bedrock_region="$(read_local_setting TAKEBOARD_BEDROCK_REGION)"
bedrock_model_id="$(read_local_setting TAKEBOARD_BEDROCK_MODEL_ID)"
bedrock_timeout="$(read_local_setting TAKEBOARD_BEDROCK_TIMEOUT_SECONDS)"

if [[ -n "${bedrock_enabled}${bedrock_region}${bedrock_model_id}${bedrock_timeout}" ]]; then
  if [[ -z "${bedrock_enabled}" || -z "${bedrock_region}" || -z "${bedrock_model_id}" || -z "${bedrock_timeout}" ]]; then
    echo "When configuring Bedrock, set all four TAKEBOARD_BEDROCK_* deployment settings together." >&2
    exit 1
  fi
  if [[ ! "${bedrock_enabled}" =~ ^(true|false|1|0|yes|no|on|off)$ ]]; then
    echo "TAKEBOARD_BEDROCK_ENABLED must be a boolean value." >&2
    exit 1
  fi
  if [[ ! "${bedrock_region}" =~ ^[A-Za-z0-9-]+$ || ! "${bedrock_model_id}" =~ ^[A-Za-z0-9:./_-]+$ || ! "${bedrock_timeout}" =~ ^[0-9]+$ ]]; then
    echo "Bedrock region, model ID, or timeout contains unsupported characters." >&2
    exit 1
  fi
fi

require_command() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "Missing required command: $1" >&2
    exit 1
  fi
}

require_command aws
require_command docker
require_command base64

account_id="$(aws sts get-caller-identity --profile "${aws_profile}" --query Account --output text)"
ecr_registry="${account_id}.dkr.ecr.${aws_region}.amazonaws.com"
git_revision="$(git rev-parse --short HEAD)"
build_stamp="$(date -u +%Y%m%d%H%M%S)"
image_tag="${TTB_IMAGE_TAG:-${git_revision}-${build_stamp}}"
image_uri="${ecr_registry}/${ecr_repository}:${image_tag}"

if [[ -z "${instance_id}" ]]; then
  matching_instances_text="$(
    aws ec2 describe-instances \
      --profile "${aws_profile}" \
      --region "${aws_region}" \
      --filters "Name=tag:Name,Values=${instance_name}" "Name=instance-state-name,Values=running" \
      --query 'Reservations[].Instances[].InstanceId' \
      --output text
  )"
  read -r -a matching_instances <<< "${matching_instances_text}"

  if [[ "${#matching_instances[@]}" -ne 1 || -z "${matching_instances[0]}" ]]; then
    echo "Expected one running instance tagged Name=${instance_name}; found ${#matching_instances[@]}." >&2
    echo "Set TTB_DEV_INSTANCE_ID to deploy to an explicit instance." >&2
    exit 1
  fi

  instance_id="${matching_instances[0]}"
fi

echo "Deploying ${image_uri} to ${instance_id}"

aws ecr get-login-password --region "${aws_region}" --profile "${aws_profile}" \
  | docker login --username AWS --password-stdin "${ecr_registry}"

docker buildx build \
  --platform linux/amd64 \
  --push \
  --tag "${image_uri}" \
  .

remote_bootstrap="$(cat <<EOF
set -euo pipefail
image='${image_uri}'
registry='${ecr_registry}'
region='${aws_region}'
deployment_dir='/opt/ttb'
bedrock_enabled='${bedrock_enabled}'
bedrock_region='${bedrock_region}'
bedrock_model_id='${bedrock_model_id}'
bedrock_timeout='${bedrock_timeout}'

aws ecr get-login-password --region "\${region}" | docker login --username AWS --password-stdin "\${registry}"
docker pull "\${image}"
docker rm -f ttb-deploy-script >/dev/null 2>&1 || true
docker create --name ttb-deploy-script "\${image}" >/dev/null
docker cp ttb-deploy-script:/app/deploy/dev/remote_deploy.sh "\${deployment_dir}/remote_deploy.sh"
docker rm ttb-deploy-script >/dev/null
chmod 700 "\${deployment_dir}/remote_deploy.sh"

if [[ -n "\${bedrock_enabled}\${bedrock_region}\${bedrock_model_id}\${bedrock_timeout}" ]]; then
  upsert_setting() {
    local setting="\$1"
    local value="\$2"
    if grep -q "^\${setting}=" "\${deployment_dir}/.env"; then
      sed -i "s|^\${setting}=.*|\${setting}=\${value}|" "\${deployment_dir}/.env"
    else
      printf '\n%s=%s\n' "\${setting}" "\${value}" >> "\${deployment_dir}/.env"
    fi
  }
  upsert_setting TAKEBOARD_BEDROCK_ENABLED "\${bedrock_enabled}"
  upsert_setting TAKEBOARD_BEDROCK_REGION "\${bedrock_region}"
  upsert_setting TAKEBOARD_BEDROCK_MODEL_ID "\${bedrock_model_id}"
  upsert_setting TAKEBOARD_BEDROCK_TIMEOUT_SECONDS "\${bedrock_timeout}"
  echo "Synchronized Bedrock moderation settings from ${local_env_file}."
fi

exec "\${deployment_dir}/remote_deploy.sh" "\${image}"
EOF
)"

encoded_bootstrap="$(printf '%s' "${remote_bootstrap}" | base64 | tr -d '\n')"
command_id="$(
  aws ssm send-command \
    --profile "${aws_profile}" \
    --region "${aws_region}" \
    --instance-ids "${instance_id}" \
    --document-name "AWS-RunShellScript" \
    --comment "Deploy ${ecr_repository}:${image_tag}" \
    --timeout-seconds 1800 \
    --parameters "commands=echo ${encoded_bootstrap} | base64 --decode | bash" \
    --query 'Command.CommandId' \
    --output text
)"

echo "Running remote deployment through SSM (${command_id})"

if ! aws ssm wait command-executed \
  --profile "${aws_profile}" \
  --region "${aws_region}" \
  --command-id "${command_id}" \
  --instance-id "${instance_id}"; then
  aws ssm get-command-invocation \
    --profile "${aws_profile}" \
    --region "${aws_region}" \
    --command-id "${command_id}" \
    --instance-id "${instance_id}" \
    --query '{Status:Status,Output:StandardOutputContent,Error:StandardErrorContent}' \
    --output json
  exit 1
fi

aws ssm get-command-invocation \
  --profile "${aws_profile}" \
  --region "${aws_region}" \
  --command-id "${command_id}" \
  --instance-id "${instance_id}" \
  --query '{Status:Status,Output:StandardOutputContent,Error:StandardErrorContent}' \
  --output json

echo "Dev deployment completed: ${image_uri}"
