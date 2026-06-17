data "aws_caller_identity" "current" {}

# --- Execution role assumed by the AgentCore Runtime --------------------------------
data "aws_iam_policy_document" "assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["bedrock-agentcore.amazonaws.com"]
    }
    condition {
      test     = "StringEquals"
      variable = "aws:SourceAccount"
      values   = [data.aws_caller_identity.current.account_id]
    }
  }
}

resource "aws_iam_role" "exec" {
  name               = "${var.name_prefix}-exec"
  assume_role_policy = data.aws_iam_policy_document.assume.json
  tags               = var.tags
}

# Least privilege: invoke the configured models, the one history table, Memory, the Code
# Interpreter, ECR pull, and write logs.
data "aws_iam_policy_document" "exec" {
  statement {
    sid       = "InvokeModels"
    actions   = ["bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream"]
    resources = var.model_arns
  }
  statement {
    sid = "ScanHistory"
    actions = [
      "dynamodb:PutItem",
      "dynamodb:GetItem",
      "dynamodb:UpdateItem",
      "dynamodb:Query",
    ]
    resources = [var.dynamodb_table_arn]
  }
  statement {
    sid = "MemoryAndInterpreter"
    actions = [
      "bedrock-agentcore:CreateEvent",
      "bedrock-agentcore:RetrieveMemoryRecords",
      "bedrock-agentcore:StartCodeInterpreterSession",
      "bedrock-agentcore:InvokeCodeInterpreter",
      "bedrock-agentcore:StopCodeInterpreterSession",
    ]
    resources = ["*"]
  }
  statement {
    sid       = "EcrPull"
    actions   = ["ecr:GetAuthorizationToken", "ecr:BatchGetImage", "ecr:GetDownloadUrlForLayer"]
    resources = ["*"]
  }
  statement {
    sid       = "Logs"
    actions   = ["logs:CreateLogGroup", "logs:CreateLogStream", "logs:PutLogEvents"]
    resources = ["arn:aws:logs:${var.region}:${data.aws_caller_identity.current.account_id}:*"]
  }
}

resource "aws_iam_role_policy" "exec" {
  name   = "${var.name_prefix}-exec"
  role   = aws_iam_role.exec.id
  policy = data.aws_iam_policy_document.exec.json
}

# --- Runtime provisioning seam ------------------------------------------------------
# AgentCore Runtime has no first-class Terraform resource yet, so we drive the control-plane
# CLI from a null_resource. It (re)applies whenever the image digest changes, which mints a
# new runtime version so the DEFAULT endpoint serves the new image (a plain push is NOT
# enough — see module README).
resource "null_resource" "runtime" {
  triggers = {
    image_digest = var.image_digest
    image_uri    = var.image_uri
    role_arn     = aws_iam_role.exec.arn
    issuer       = var.cognito_issuer_url
    client_id    = var.cognito_client_id
  }

  provisioner "local-exec" {
    interpreter = ["/bin/bash", "-c"]
    command     = <<-EOT
      set -euo pipefail
      "${path.module}/deploy_runtime.sh" \
        --name "${var.name_prefix}" \
        --region "${var.region}" \
        --image "${var.image_uri}" \
        --role-arn "${aws_iam_role.exec.arn}" \
        --issuer "${var.cognito_issuer_url}" \
        --client-id "${var.cognito_client_id}"
    EOT
  }

  depends_on = [aws_iam_role_policy.exec]
}
