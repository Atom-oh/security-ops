output "table_name" {
  value = aws_dynamodb_table.scan_history.name
}

output "table_arn" {
  value = aws_dynamodb_table.scan_history.arn
}
