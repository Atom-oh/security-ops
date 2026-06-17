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

  tags = var.tags
}
