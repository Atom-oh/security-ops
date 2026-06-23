# module: agentcore

Provisions the FSI-Mythos AgentCore Runtime and its least-privilege execution role.

## The seam: no first-class Terraform resource

Amazon Bedrock AgentCore Runtime has **no native Terraform resource** at the time of
writing. This module therefore:

1. Creates the IAM **execution role** (Terraform-managed, least privilege: invoke the
   configured Bedrock models, the one DynamoDB history table, AgentCore Memory + Code
   Interpreter, ECR pull, CloudWatch Logs).
2. Drives the **control-plane CLI** from a `null_resource` (`deploy_runtime.sh`) to
   create-or-update the runtime with a **Cognito JWT inbound authorizer**.

### Why `update-agent-runtime` matters
Pushing a new image to ECR does **not** change what the runtime serves. The runtime must be
updated to mint a new version so the `DEFAULT` endpoint picks up the new digest. The
`null_resource` re-runs whenever `image_digest` changes, calling `update-agent-runtime`.

### Inbound auth wiring
`cognito_issuer_url` + `cognito_client_id` (from the `auth` module) are injected into the
authorizer config (`discoveryUrl` + `allowedClients`). The SPA sends the Cognito **access**
token; the authorizer validates its `client_id` claim against `allowedClients`.

### Region / model profiles
The runtime trusts its container `AWS_REGION`. In Seoul (`ap-northeast-2`) the app resolves
`apac.*` Opus inference profiles; pass the matching `model_arns` (default `["*"]` for the
demo — tighten for production).

### Caveats
- The exact `bedrock-agentcore-control` subcommands/flags vary by AWS CLI version — verify
  and adjust `deploy_runtime.sh` if a call errors at apply.
- **Seoul availability**: confirm AgentCore Runtime + the `apac.*` Opus profiles are
  available in `ap-northeast-2` at deploy time. If not, set the env region/model vars to
  `us-west-2` / `us.*` — no code changes needed.
- The runtime ARN is not in Terraform state; read it post-apply via `list-agent-runtimes`
  (see `outputs.tf`).
