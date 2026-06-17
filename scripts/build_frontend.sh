#!/usr/bin/env bash
# Build the SPA from Terraform outputs (Cognito/runtime), sync to S3, invalidate CloudFront.
set -euo pipefail
source "$(dirname "$0")/_common.sh"
maybe_assume_role

cd "$ROOT/infra/envs/seoul"
BUCKET=$(terraform output -raw web_bucket)
DIST_ID=$(terraform output -raw cloudfront_distribution_id)
POOL_ID=$(terraform output -raw user_pool_id)
CLIENT_ID=$(terraform output -raw user_pool_client_id)

# Resolve the runtime ARN from the control plane (not in TF state).
RUNTIME_NAME=$(terraform output -raw agentcore_runtime_name)
RUNTIME_ARN=$(aws bedrock-agentcore-control list-agent-runtimes --region "$REGION" \
  --query "agentRuntimes[?agentRuntimeName=='${RUNTIME_NAME}'].agentRuntimeArn | [0]" --output text)

cd "$ROOT/frontend"
cat > .env <<ENV
VITE_REGION=${REGION}
VITE_USER_POOL_ID=${POOL_ID}
VITE_USER_POOL_CLIENT_ID=${CLIENT_ID}
VITE_RUNTIME_ARN=${RUNTIME_ARN}
ENV

echo "[frontend] building"
npm ci
npm run build

echo "[frontend] syncing to s3://${BUCKET}"
aws s3 sync dist "s3://${BUCKET}" --delete

echo "[frontend] invalidating CloudFront ${DIST_ID}"
aws cloudfront create-invalidation --distribution-id "$DIST_ID" --paths '/*' >/dev/null
echo "[frontend] done."
