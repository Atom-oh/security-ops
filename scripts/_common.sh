#!/usr/bin/env bash
# Shared helpers for the deploy scripts. Source this, don't run it.
set -euo pipefail

# Optionally assume a deploy role (AWS_ROLE_ARN) before any AWS call; otherwise use ambient
# credentials. Exports temporary creds into the environment.
maybe_assume_role() {
  [ -n "${AWS_ROLE_ARN:-}" ] || return 0
  echo "[deploy] assuming role ${AWS_ROLE_ARN}"
  local creds
  creds=$(aws sts assume-role --role-arn "$AWS_ROLE_ARN" \
    --role-session-name fsi-mythos-deploy --query Credentials --output json)
  AWS_ACCESS_KEY_ID=$(echo "$creds" | python3 -c 'import json,sys;print(json.load(sys.stdin)["AccessKeyId"])')
  AWS_SECRET_ACCESS_KEY=$(echo "$creds" | python3 -c 'import json,sys;print(json.load(sys.stdin)["SecretAccessKey"])')
  AWS_SESSION_TOKEN=$(echo "$creds" | python3 -c 'import json,sys;print(json.load(sys.stdin)["SessionToken"])')
  export AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY AWS_SESSION_TOKEN
}

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REGION="${AWS_REGION:-ap-northeast-2}"
REPO_NAME="${REPO_NAME:-fsi-mythos}"
