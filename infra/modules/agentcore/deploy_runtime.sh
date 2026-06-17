#!/usr/bin/env bash
# Create-or-update the AgentCore Runtime via the control-plane CLI, configuring a Cognito
# JWT inbound authorizer. Idempotent: creates the runtime if absent, otherwise mints a new
# version pointing at the (new) image so the DEFAULT endpoint serves it.
#
# NOTE: the exact `bedrock-agentcore-control` subcommand/flag names vary by CLI version.
# Verify against your installed AWS CLI and adjust if a call errors at apply time.
set -euo pipefail

NAME="" REGION="" IMAGE="" ROLE_ARN="" ISSUER="" CLIENT_ID=""
while [ $# -gt 0 ]; do
  case "$1" in
    --name) NAME="$2"; shift 2;;
    --region) REGION="$2"; shift 2;;
    --image) IMAGE="$2"; shift 2;;
    --role-arn) ROLE_ARN="$2"; shift 2;;
    --issuer) ISSUER="$2"; shift 2;;
    --client-id) CLIENT_ID="$2"; shift 2;;
    *) echo "unknown arg: $1" >&2; exit 2;;
  esac
done

# Build JSON safely with jq so quotes/metacharacters in inputs can't break the payload.
AUTH_CONFIG=$(jq -n --arg iss "$ISSUER" --arg clid "$CLIENT_ID" \
  '{customJWTAuthorizer:{discoveryUrl:($iss + "/.well-known/openid-configuration"),allowedClients:[$clid]}}')
ARTIFACT=$(jq -n --arg uri "$IMAGE" '{containerConfiguration:{containerUri:$uri}}')
NET_CONFIG='{"networkMode":"PUBLIC"}'

# Robust existence check: trim whitespace/newlines; treat empty or "None" as absent.
existing=$(aws bedrock-agentcore-control list-agent-runtimes --region "$REGION" \
  --query "agentRuntimes[?agentRuntimeName=='${NAME}'].agentRuntimeId | [0]" \
  --output text 2>/dev/null | head -n1 | tr -d '[:space:]' || true)

if [ -z "$existing" ] || [ "$existing" = "None" ]; then
  echo "[agentcore] creating runtime ${NAME}"
  aws bedrock-agentcore-control create-agent-runtime --region "$REGION" \
    --agent-runtime-name "$NAME" \
    --role-arn "$ROLE_ARN" \
    --network-configuration "$NET_CONFIG" \
    --authorizer-configuration "$AUTH_CONFIG" \
    --agent-runtime-artifact "$ARTIFACT"
else
  echo "[agentcore] updating runtime ${NAME} (${existing}) → new version"
  aws bedrock-agentcore-control update-agent-runtime --region "$REGION" \
    --agent-runtime-id "$existing" \
    --role-arn "$ROLE_ARN" \
    --network-configuration "$NET_CONFIG" \
    --authorizer-configuration "$AUTH_CONFIG" \
    --agent-runtime-artifact "$ARTIFACT"
fi
