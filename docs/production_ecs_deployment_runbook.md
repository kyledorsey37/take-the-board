# Production ECS deployment runbook

Use `deploy/aws/deploy_prod_ecs.sh` for normal application releases. It builds
the current checkout for ECS/Fargate, pushes a Git-SHA-tagged image to the
production ECR repository, copies the currently running task definition, and
changes only the selected container image before updating the ECS service.

The script does not run CloudFormation and does not replace the task
definition's environment variables, Secrets Manager references, logging, task
roles, networking, or resource sizing.

## Prerequisites

- AWS CLI profile `ttb-prod-builder` can call STS, ECR, and the required ECS
  read/register/update operations in account `102913100093`.
- Docker with Buildx, Git, `jq`, and `curl` are installed.
- The intended release is committed. The script refuses a dirty worktree by
  default so the image tag identifies the source that was deployed.

## Deploy

From the repository root:

```bash
./deploy/aws/deploy_prod_ecs.sh
```

Type `deploy` at the confirmation prompt. For an intentional non-interactive
run, provide the explicit confirmation flag:

```bash
./deploy/aws/deploy_prod_ecs.sh --yes
```

The script verifies the AWS account before pushing anything, waits for the ECS
service to become stable, confirms that the new task definition is active, and
requests a public smoke check for `/schools/alabama/`.

Useful overrides are available without editing the script:

```bash
TTB_AWS_PROFILE=ttb-prod-builder \
TTB_PROD_SMOKE_URL=https://taketheboard.com/schools/alabama/ \
./deploy/aws/deploy_prod_ecs.sh --yes
```

For an emergency test of uncommitted local changes only, use
`--allow-dirty`. Prefer committing the release and deploying the full Git SHA.

## Rollback

The script prints the previous task-definition ARN. If the new deployment is
unhealthy, restore that revision directly through ECS:

```bash
aws ecs update-service \
  --profile ttb-prod-builder \
  --region us-east-1 \
  --cluster takeboard-prod \
  --service takeboard-prod-web \
  --task-definition <previous-task-definition-arn>
```

After a rollback, wait for service stability and repeat the public smoke check.
