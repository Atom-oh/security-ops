#!/usr/bin/env bash
# Full ordered deploy: infra → backend image → frontend. Honors optional AWS_ROLE_ARN.
# Order matters (Architecture §08): infra first (ECR/runtime/web), then push the backend
# image + update the runtime, then build/sync the SPA which needs the runtime ARN.
set -euo pipefail
source "$(dirname "$0")/_common.sh"
maybe_assume_role

# Ordering matters: the AgentCore runtime can't be created until its image exists in ECR.
echo "==> 1/3 bootstrap ECR registry"
cd "$ROOT/infra/envs/seoul"
terraform init -input=false
terraform apply -input=false -auto-approve -target=module.ecr

echo "==> 2/3 backend image build + push, then full apply (creates runtime with real image)"
"$ROOT/scripts/build_push_backend.sh"

echo "==> 3/3 frontend build + s3 sync + invalidation"
"$ROOT/scripts/build_frontend.sh"

echo "==> deploy complete"
cd "$ROOT/infra/envs/seoul"
echo "SPA: https://$(terraform output -raw cloudfront_domain)"
