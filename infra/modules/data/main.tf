# Per-user scan history. userId (PK) isolates each user's data; scanId (SK) sorts newest-first.
resource "aws_dynamodb_table" "scan_history" {
  name         = var.table_name
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "userId"
  range_key    = "scanId"

  attribute {
    name = "userId"
    type = "S"
  }
  attribute {
    name = "scanId"
    type = "S"
  }

  point_in_time_recovery {
    enabled = true
  }

  server_side_encryption {
    enabled = true
  }

  # ADR-001: the versioned prompt store reuses this table (PK=PROMPT#<agentKey>). Those items
  # are an immutable audit record and MUST NEVER be expired — do not add a TTL attribute here.
  tags = var.tags
}

# --- Durable async scan dispatch (scan-stall fix) -----------------------------------------
# scan_async enqueues here; a long-running Fargate worker consumes and runs the 8-phase scan
# to completion (the AgentCore runtime freezes after the entrypoint returns, so the scan must
# NOT run in-process there). DLQ + redrive bound poison messages.
resource "aws_sqs_queue" "scan_worker_dlq" {
  name                      = "${var.table_name}-scan-worker-dlq"
  message_retention_seconds = 1209600 # 14 days
  sqs_managed_sse_enabled   = true
  tags                      = var.tags
}

resource "aws_sqs_queue" "scan_worker" {
  name = "${var.table_name}-scan-worker"
  # Visibility timeout must exceed the worst-case scan duration so a still-running scan is not
  # redelivered mid-flight (the lease would skip it, but this avoids needless churn).
  visibility_timeout_seconds = var.scan_visibility_timeout_seconds
  message_retention_seconds  = 86400 # 1 day
  sqs_managed_sse_enabled    = true
  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.scan_worker_dlq.arn
    maxReceiveCount     = var.scan_max_receive_count
  })
  tags = var.tags
}
