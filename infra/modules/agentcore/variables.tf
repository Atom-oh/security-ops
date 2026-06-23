variable "name_prefix" {
  type    = string
  default = "fsi_mythos" # AgentCore runtime names allow [a-zA-Z0-9_]
}

variable "region" {
  type = string
}

variable "image_uri" {
  type        = string
  description = "Full ECR image URI (repo:tag or repo@digest) the runtime should serve."
}

variable "image_digest" {
  type        = string
  description = "Image digest/tag used as the null_resource trigger so a new push → update-agent-runtime."
  default     = ""
}

variable "dynamodb_table_arn" {
  type = string
}

variable "scan_worker_queue_arn" {
  type        = string
  default     = ""
  description = "SQS scan-worker queue ARN the durable Fargate worker consumes (ADR-001 worker role)."
}

variable "ecr_repository_arn" {
  type        = string
  description = "ECR repo ARN the runtime pulls from (scopes the data-plane pull permission)."
}

variable "model_arns" {
  type        = list(string)
  description = "Bedrock model/inference-profile ARNs the runtime may invoke."
  default     = ["*"]
}

variable "cognito_issuer_url" {
  type = string
}

variable "cognito_client_id" {
  type = string
}

variable "tags" {
  type    = map(string)
  default = {}
}
