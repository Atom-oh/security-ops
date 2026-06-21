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
  # GetAuthorizationToken is account-wide by API design; the data-plane pulls are scoped to
  # the one repository.
  statement {
    sid       = "EcrAuth"
    actions   = ["ecr:GetAuthorizationToken"]
    resources = ["*"]
  }
  statement {
    sid       = "EcrPull"
    actions   = ["ecr:BatchGetImage", "ecr:GetDownloadUrlForLayer"]
    resources = [var.ecr_repository_arn]
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

# --- Scan-worker role (ADR-001 IAM read/write split) --------------------------------
# Forward-looking role for the durable Fargate scan worker. It reads/writes scan-history
# items but is explicitly DENIED any access to PROMPT# items: the worker receives the
# resolved prompts INLINE in the SQS message (hash-verified in code) and never needs to read
# or write the prompt store. Until the Fargate worker is provisioned as this separate
# principal, the read/write split is additionally enforced at the code level (scan/worker
# code never calls PromptStore writes; the inline-body design removes any worker PROMPT# read).
data "aws_iam_policy_document" "scan_worker_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["ecs-tasks.amazonaws.com"]
    }
    condition {
      test     = "StringEquals"
      variable = "aws:SourceAccount"
      values   = [data.aws_caller_identity.current.account_id]
    }
  }
}

resource "aws_iam_role" "scan_worker" {
  name               = "${var.name_prefix}-scan-worker"
  assume_role_policy = data.aws_iam_policy_document.scan_worker_assume.json
  tags               = var.tags
}

data "aws_iam_policy_document" "scan_worker" {
  statement {
    sid       = "InvokeModels"
    actions   = ["bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream"]
    resources = var.model_arns
  }
  statement {
    sid       = "ScanHistoryRW"
    actions   = ["dynamodb:PutItem", "dynamodb:GetItem", "dynamodb:UpdateItem", "dynamodb:Query"]
    resources = [var.dynamodb_table_arn]
  }
  # Explicit Deny on prompt items — an exclusion MUST be a Deny because user partitions are
  # unbounded sub UUIDs and cannot be expressed as a restrictive Allow. LeadingKeys matches the
  # partition-key value (PROMPT#<agent>); StringLike supports the wildcard. Covers reads too.
  statement {
    sid    = "DenyPromptItems"
    effect = "Deny"
    actions = [
      "dynamodb:PutItem", "dynamodb:UpdateItem", "dynamodb:DeleteItem", "dynamodb:BatchWriteItem",
      "dynamodb:GetItem", "dynamodb:Query", "dynamodb:BatchGetItem",
    ]
    resources = [var.dynamodb_table_arn]
    condition {
      test     = "StringLike"
      variable = "dynamodb:LeadingKeys"
      values   = ["PROMPT#*"]
    }
  }
  dynamic "statement" {
    for_each = var.scan_worker_queue_arn == "" ? [] : [var.scan_worker_queue_arn]
    content {
      sid       = "WorkerSqs"
      actions   = ["sqs:ReceiveMessage", "sqs:DeleteMessage", "sqs:GetQueueAttributes"]
      resources = [statement.value]
    }
  }
  statement {
    sid       = "Logs"
    actions   = ["logs:CreateLogGroup", "logs:CreateLogStream", "logs:PutLogEvents"]
    resources = ["arn:aws:logs:${var.region}:${data.aws_caller_identity.current.account_id}:*"]
  }
}

resource "aws_iam_role_policy" "scan_worker" {
  name   = "${var.name_prefix}-scan-worker"
  role   = aws_iam_role.scan_worker.id
  policy = data.aws_iam_policy_document.scan_worker.json
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

  # Inputs are passed via the environment (not string-interpolated into the command) to
  # avoid shell injection from any value containing quotes/metacharacters.
  provisioner "local-exec" {
    interpreter = ["/bin/bash", "-c"]
    command     = "exec \"$SCRIPT\" --name \"$RT_NAME\" --region \"$RT_REGION\" --image \"$RT_IMAGE\" --role-arn \"$RT_ROLE\" --issuer \"$RT_ISSUER\" --client-id \"$RT_CLIENT\""
    environment = {
      SCRIPT    = "${path.module}/deploy_runtime.sh"
      RT_NAME   = var.name_prefix
      RT_REGION = var.region
      RT_IMAGE  = var.image_uri
      RT_ROLE   = aws_iam_role.exec.arn
      RT_ISSUER = var.cognito_issuer_url
      RT_CLIENT = var.cognito_client_id
    }
  }

  depends_on = [aws_iam_role_policy.exec]
}
