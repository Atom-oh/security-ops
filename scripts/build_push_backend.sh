#!/usr/bin/env bash
# Build the ARM64 backend image, push to ECR, and update the AgentCore runtime to the new
# digest. Requires the infra to exist (ECR repo + runtime). Honors optional AWS_ROLE_ARN.
set -euo pipefail
source "$(dirname "$0")/_common.sh"
maybe_assume_role

ACCOUNT=$(aws sts get-caller-identity --query Account --output text)
REGISTRY="${ACCOUNT}.dkr.ecr.${REGION}.amazonaws.com"
IMAGE="${REGISTRY}/${REPO_NAME}:latest"

echo "[backend] logging in to ECR ${REGISTRY}"
aws ecr get-login-password --region "$REGION" | docker login --username AWS --password-stdin "$REGISTRY"

echo "[backend] building ARM64 image"
docker buildx build --platform linux/arm64 -t "$IMAGE" --push "$ROOT/backend"

DIGEST=$(aws ecr describe-images --region "$REGION" --repository-name "$REPO_NAME" \
  --image-ids imageTag=latest --query 'imageDetails[0].imageDigest' --output text)
echo "[backend] pushed digest ${DIGEST}"

echo "[backend] terraform apply with new image (only the changed image digest → update-agent-runtime)"
cd "$ROOT/infra/envs/seoul"
terraform apply -input=false -auto-approve \
  -var "image_uri=${REGISTRY}/${REPO_NAME}@${DIGEST}" \
  -var "image_digest=${DIGEST}"

echo "[backend] done."
