#!/usr/bin/env bash

set -euo pipefail

usage() {
  cat <<'EOF'
Usage: setup_bid_finalization_sqs.sh [options]

Creates an SQS FIFO bid-finalization queue, its FIFO DLQ, and (when supplied)
the least-privilege worker-role policy.

Options:
  --environment NAME  Environment label (default: dev)
  --profile NAME       AWS CLI profile
  --region REGION      AWS region (default: us-east-1)
  --role-name NAME     IAM worker role to receive the queue policy
  --queue-name NAME    Source queue name (must end in .fifo)
  --dlq-name NAME      DLQ name (must end in .fifo)
  --help               Show this help
EOF
}

environment="${TTB_ENVIRONMENT:-dev}"
profile="${TTB_AWS_PROFILE:-}"
region="${TTB_AWS_REGION:-us-east-1}"
role_name="${TTB_SQS_WORKER_ROLE_NAME:-}"
queue_name="${TTB_SQS_QUEUE_NAME:-}"
dlq_name="${TTB_SQS_DLQ_NAME:-}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --environment) environment="$2"; shift 2 ;;
    --profile) profile="$2"; shift 2 ;;
    --region) region="$2"; shift 2 ;;
    --role-name) role_name="$2"; shift 2 ;;
    --queue-name) queue_name="$2"; shift 2 ;;
    --dlq-name) dlq_name="$2"; shift 2 ;;
    --help) usage; exit 0 ;;
    *) echo "Unknown option: $1" >&2; usage >&2; exit 2 ;;
  esac
done

queue_name="${queue_name:-takeboard-${environment}-bid-finalization.fifo}"
dlq_name="${dlq_name:-takeboard-${environment}-bid-finalization-dlq.fifo}"

if [[ "$queue_name" != *.fifo || "$dlq_name" != *.fifo ]]; then
  echo "Source and DLQ names must end in .fifo." >&2
  exit 2
fi
if [[ "$environment" == "prod" && -z "$role_name" ]]; then
  echo "--role-name is required for production." >&2
  exit 2
fi
if ! command -v aws >/dev/null 2>&1; then
  echo "Missing required command: aws" >&2
  exit 1
fi
if ! command -v jq >/dev/null 2>&1; then
  echo "Missing required command: jq" >&2
  exit 1
fi

aws_args=(--region "$region")
if [[ -n "$profile" ]]; then
  aws_args+=(--profile "$profile")
fi

echo "Using AWS profile=${profile:-default} region=$region environment=$environment"
account_id="$(aws "${aws_args[@]}" sts get-caller-identity --query Account --output text)"

dlq_attributes="$(jq -cn '{
  FifoQueue:"true",
  ContentBasedDeduplication:"false",
  DeduplicationScope:"messageGroup",
  FifoThroughputLimit:"perMessageGroupId",
  MessageRetentionPeriod:"1209600",
  SqsManagedSseEnabled:"true"
}')"

dlq_url="$(aws "${aws_args[@]}" sqs create-queue \
  --queue-name "$dlq_name" \
  --attributes "$dlq_attributes" \
  --tags "Environment=$environment,Service=take-the-board,Component=bid-finalization-dlq" \
  --query QueueUrl --output text)"

dlq_arn="$(aws "${aws_args[@]}" sqs get-queue-attributes \
  --queue-url "$dlq_url" --attribute-names QueueArn \
  --query Attributes.QueueArn --output text)"

queue_attributes="$(jq -cn --arg dlq_arn "$dlq_arn" '{
  FifoQueue:"true",
  ContentBasedDeduplication:"false",
  DeduplicationScope:"messageGroup",
  FifoThroughputLimit:"perMessageGroupId",
  VisibilityTimeout:"120",
  ReceiveMessageWaitTimeSeconds:"20",
  MessageRetentionPeriod:"345600",
  RedrivePolicy: ({deadLetterTargetArn:$dlq_arn,maxReceiveCount:"5"} | tojson),
  SqsManagedSseEnabled:"true"
}')"

queue_url="$(aws "${aws_args[@]}" sqs create-queue \
  --queue-name "$queue_name" \
  --attributes "$queue_attributes" \
  --tags "Environment=$environment,Service=take-the-board,Component=bid-finalization" \
  --query QueueUrl --output text)"

queue_arn="$(aws "${aws_args[@]}" sqs get-queue-attributes \
  --queue-url "$queue_url" --attribute-names QueueArn \
  --query Attributes.QueueArn --output text)"

dlq_allow_attributes="$(jq -cn --arg source_arn "$queue_arn" '{
  RedriveAllowPolicy: ({
    redrivePermission:"byQueue",
    sourceQueueArns:[$source_arn]
  } | tojson)
}')"

aws "${aws_args[@]}" sqs set-queue-attributes \
  --queue-url "$dlq_url" --attributes "$dlq_allow_attributes"

if [[ -n "$role_name" ]]; then
  aws "${aws_args[@]}" iam get-role --role-name "$role_name" >/dev/null
  worker_policy="$(jq -cn --arg queue_arn "$queue_arn" '{
    Version:"2012-10-17",
    Statement:[{
      Sid:"TakeBoardBidFinalizationSqs",
      Effect:"Allow",
      Action:[
        "sqs:ReceiveMessage",
        "sqs:DeleteMessage",
        "sqs:ChangeMessageVisibility",
        "sqs:GetQueueAttributes",
        "sqs:SendMessage"
      ],
      Resource:$queue_arn
    }]
  }')"
  aws "${aws_args[@]}" iam put-role-policy \
    --role-name "$role_name" \
    --policy-name "takeboard-${environment}-bid-finalization-sqs" \
    --policy-document "$worker_policy"
fi

echo "Created or confirmed account=$account_id"
echo "Queue URL: $queue_url"
echo "DLQ URL:   $dlq_url"
echo
echo "Hosted environment values:"
echo "TAKEBOARD_BID_FINALIZATION_MODE=sqs_fifo"
echo "TAKEBOARD_SQS_BID_FINALIZATION_QUEUE_URL=$queue_url"
echo "TAKEBOARD_SQS_BID_FINALIZATION_REGION=$region"
echo "TAKEBOARD_SQS_BID_FINALIZATION_WAIT_SECONDS=20"
echo "TAKEBOARD_SQS_BID_FINALIZATION_VISIBILITY_TIMEOUT_SECONDS=120"
echo "TAKEBOARD_SQS_BID_FINALIZATION_RETRY_VISIBILITY_SECONDS=30"
echo "TAKEBOARD_SQS_BID_FINALIZATION_MAX_RECEIVE_COUNT=5"
