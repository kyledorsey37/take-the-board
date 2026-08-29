#!/usr/bin/env bash

set -euo pipefail

aws_profile="${TTB_AWS_PROFILE:-ttb-dev}"
aws_region="${TTB_AWS_REGION:-us-east-1}"
ecr_repository="${TTB_ECR_REPOSITORY:-ttb-dev}"
instance_name="${TTB_DEV_INSTANCE_NAME:-ttb-dev-ec2}"
instance_id="${TTB_DEV_INSTANCE_ID:-}"

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

aws ecr get-login-password --region "\${region}" | docker login --username AWS --password-stdin "\${registry}"
docker pull "\${image}"
docker rm -f ttb-deploy-script >/dev/null 2>&1 || true
docker create --name ttb-deploy-script "\${image}" >/dev/null
docker cp ttb-deploy-script:/app/deploy/dev/remote_deploy.sh "\${deployment_dir}/remote_deploy.sh"
docker rm ttb-deploy-script >/dev/null
chmod 700 "\${deployment_dir}/remote_deploy.sh"
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
