variable "region" {
  type    = string
  default = "ap-northeast-2" # Seoul — data sovereignty
}

variable "name_prefix" {
  type    = string
  default = "fsi-mythos"
}

variable "runtime_name" {
  type    = string
  default = "fsi_mythos" # AgentCore runtime name charset: [a-zA-Z0-9_]
}

variable "image_uri" {
  type        = string
  description = "ECR image URI for the backend (set after build/push)."
  default     = "PLACEHOLDER_SET_AFTER_PUSH"
}

variable "image_digest" {
  type        = string
  description = "Backend image digest/tag — changing it triggers update-agent-runtime."
  default     = "bootstrap"
}

# Bedrock model/inference-profile ARNs the runtime may invoke. Defaults are scoped to Claude
# foundation models + cross-region inference profiles (not a blanket "*"). Tighten further to
# the exact apac.* Opus profile ARNs for production.
variable "model_arns" {
  type = list(string)
  default = [
    "arn:aws:bedrock:*::foundation-model/anthropic.claude-*",
    "arn:aws:bedrock:*:*:inference-profile/*anthropic.claude-*",
    # v2.2 cross-family ensemble: OpenAI models via the bedrock-mantle endpoint (us-east-1/2).
    "arn:aws:bedrock:*::foundation-model/openai.*",
    "arn:aws:bedrock:*:*:inference-profile/*openai.*",
  ]
}

variable "tags" {
  type = map(string)
  default = {
    project = "fsi-mythos"
    env     = "seoul"
  }
}
