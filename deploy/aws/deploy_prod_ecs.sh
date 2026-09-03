#!/usr/bin/env bash

set -euo pipefail

usage() {
  cat <<'EOF'
Usage: ./deploy/aws/deploy_prod_ecs.sh [options]

Build and deploy the current checkout to the production ECS service. This
script updates ECR and ECS directly; it does not run CloudFormation.

Options:
  --tag TAG          Use TAG instead of the current full Git SHA.
  --allow-dirty      Allow uncommitted files in the build context. Use only
                     when intentionally deploying local, uncommitted changes.
  --yes              Skip the interactive production confirmation.
  -h, --help         Show this help.

Environment overrides:
  TTB_AWS_PROFILE, TTB_AWS_REGION, TTB_AWS_ACCOUNT_ID
  TTB_ECR_REPOSITORY, TTB_ECS_CLUSTER, TTB_ECS_SERVICE
  TTB_ECS_CONTAINER_NAME, TTB_PROD_SMOKE_URL, TTB_IMAGE_TAG

The default production target is account 102913100093, us-east-1,
takeboard-prod/takeboard-prod-web, using AWS profile ttb-prod-builder.
EOF
}

die() {
  echo "Error: $*" >&2
  exit 1
}

require_command() {
  command -v "$1" >/dev/null 2>&1 || die "Missing required command: $1"
}

allow_dirty=0
confirm=0
image_tag=""

while (($# > 0)); do
  case "$1" in
    --allow-dirty)
      allow_dirty=1
      shift
      ;;
    --tag)
      (($# >= 2)) || die "--tag requires a value"
      image_tag="$2"
      shift 2
      ;;
    --yes)
      confirm=1
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      die "Unknown option: $1 (use --help for usage)"
      ;;
  esac
done

require_command aws
require_command curl
require_command docker
require_command git
require_command jq
docker buildx version >/dev/null 2>&1 || die "Docker Buildx is required"

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd -- "${script_dir}/../.." && pwd)"
cd "${repo_root}"

aws_profile="${TTB_AWS_PROFILE:-${AWS_PROFILE:-ttb-prod-builder}}"
aws_region="${TTB_AWS_REGION:-us-east-1}"
expected_account_id="${TTB_AWS_ACCOUNT_ID:-102913100093}"
ecr_repository="${TTB_ECR_REPOSITORY:-takeboard-prod}"
ecs_cluster="${TTB_ECS_CLUSTER:-takeboard-prod}"
ecs_service="${TTB_ECS_SERVICE:-takeboard-prod-web}"
container_name="${TTB_ECS_CONTAINER_NAME:-web}"
smoke_url="${TTB_PROD_SMOKE_URL:-https://taketheboard.com/schools/alabama/}"

git_revision="$(git rev-parse --verify HEAD 2>/dev/null)" || die "Run this from a Git checkout with a commit"
if [[ -z "${image_tag}" ]]; then
  image_tag="${TTB_IMAGE_TAG:-${git_revision}}"
fi
[[ "${image_tag}" =~ ^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$ ]] || die "Image tag contains unsupported characters"

if [[ "${allow_dirty}" -eq 0 && -n "$(git status --porcelain)" ]]; then
  die "Working tree is not clean. Commit the intended release first, or pass --allow-dirty intentionally."
fi

account_id="$(aws sts get-caller-identity \
  --profile "${aws_profile}" \
  --region "${aws_region}" \
  --query Account \
  --output text)"
[[ "${account_id}" == "${expected_account_id}" ]] || die "AWS profile ${aws_profile} resolved to account ${account_id}, expected ${expected_account_id}"

service_json="$(aws ecs describe-services \
  --profile "${aws_profile}" \
  --region "${aws_region}" \
  --cluster "${ecs_cluster}" \
  --services "${ecs_service}" \
  --query 'services[0]' \
  --output json)"
jq -e 'type == "object" and .status == "ACTIVE"' <<<"${service_json}" >/dev/null \
  || die "ECS service ${ecs_service} was not found as an ACTIVE service in cluster ${ecs_cluster}"
previous_task_definition="$(jq -r '.taskDefinition' <<<"${service_json}")"
[[ -n "${previous_task_definition}" && "${previous_task_definition}" != "null" ]] \
  || die "Could not resolve the current ECS task definition"

ecr_registry="${account_id}.dkr.ecr.${aws_region}.amazonaws.com"
image_uri="${ecr_registry}/${ecr_repository}:${image_tag}"

if [[ "${confirm}" -eq 0 ]]; then
  if [[ ! -t 0 ]]; then
    die "Production deployment requires --yes in a non-interactive shell"
  fi
  echo "Production target: ${aws_profile} / ${account_id} / ${aws_region}"
  echo "ECS service: ${ecs_cluster}/${ecs_service}"
  echo "Image: ${image_uri}"
  read -r -p "Type deploy to continue: " confirmation
  [[ "${confirmation}" == "deploy" ]] || die "Deployment cancelled"
fi

temporary_dir="$(mktemp -d "${TMPDIR:-/tmp}/takeboard-prod-deploy.XXXXXX")"
cleanup() {
  rm -rf "${temporary_dir}"
}
trap cleanup EXIT

echo "Authenticating Docker to ECR..."
aws ecr get-login-password \
  --profile "${aws_profile}" \
  --region "${aws_region}" \
  | docker login --username AWS --password-stdin "${ecr_registry}"

echo "Building and pushing ${image_uri}..."
docker buildx build \
  --platform linux/amd64 \
  --push \
  --tag "${image_uri}" \
  "${repo_root}"

echo "Copying the live task definition and changing only container ${container_name} image..."
aws ecs describe-task-definition \
  --profile "${aws_profile}" \
  --region "${aws_region}" \
  --task-definition "${previous_task_definition}" \
  --query taskDefinition \
  --output json >"${temporary_dir}/live-task-definition.json"

jq --arg image "${image_uri}" --arg container "${container_name}" '
  del(
    .taskDefinitionArn,
    .revision,
    .status,
    .requiresAttributes,
    .compatibilities,
    .registeredAt,
    .registeredBy
  )
  | if any(.containerDefinitions[]; .name == $container) then
      .containerDefinitions |= map(
        if .name == $container then .image = $image else . end
      )
    else
      error("container not found in live task definition")
    end
' "${temporary_dir}/live-task-definition.json" >"${temporary_dir}/register-task-definition.json"

new_task_definition="$(aws ecs register-task-definition \
  --profile "${aws_profile}" \
  --region "${aws_region}" \
  --cli-input-json "file://${temporary_dir}/register-task-definition.json" \
  --query 'taskDefinition.taskDefinitionArn' \
  --output text)"
[[ -n "${new_task_definition}" && "${new_task_definition}" != "None" ]] \
  || die "ECS did not return a new task definition ARN"

echo "Updating ${ecs_cluster}/${ecs_service} to ${new_task_definition}..."
aws ecs update-service \
  --profile "${aws_profile}" \
  --region "${aws_region}" \
  --cluster "${ecs_cluster}" \
  --service "${ecs_service}" \
  --task-definition "${new_task_definition}" \
  --force-new-deployment \
  --query 'service.deployments[?status==`PRIMARY`].taskDefinition | [0]' \
  --output text

echo "Waiting for ECS service stability..."
if ! aws ecs wait services-stable \
  --profile "${aws_profile}" \
  --region "${aws_region}" \
  --cluster "${ecs_cluster}" \
  --services "${ecs_service}"; then
  echo "ECS did not become stable. Previous task definition: ${previous_task_definition}" >&2
  echo "Inspect the service, then roll back if needed with:" >&2
  echo "aws ecs update-service --profile ${aws_profile} --region ${aws_region} --cluster ${ecs_cluster} --service ${ecs_service} --task-definition ${previous_task_definition}" >&2
  exit 1
fi

active_task_definition="$(aws ecs describe-services \
  --profile "${aws_profile}" \
  --region "${aws_region}" \
  --cluster "${ecs_cluster}" \
  --services "${ecs_service}" \
  --query 'services[0].taskDefinition' \
  --output text)"
[[ "${active_task_definition}" == "${new_task_definition}" ]] \
  || die "ECS stabilized on ${active_task_definition}, expected ${new_task_definition}"

echo "Running production smoke check: ${smoke_url}"
curl --fail --silent --show-error --location \
  --retry 2 \
  --retry-delay 2 \
  --max-time 30 \
  --output /dev/null \
  --write-out 'HTTP %{http_code}\n' \
  "${smoke_url}"

echo "Production deployment completed."
echo "Previous task definition: ${previous_task_definition}"
echo "Active task definition: ${new_task_definition}"
