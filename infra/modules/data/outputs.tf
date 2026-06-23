output "table_name" {
  value = aws_dynamodb_table.scan_history.name
}

output "table_arn" {
  value = aws_dynamodb_table.scan_history.arn
}

output "scan_worker_queue_url" {
  value = aws_sqs_queue.scan_worker.url
}

output "scan_worker_queue_arn" {
  value = aws_sqs_queue.scan_worker.arn
}

output "scan_worker_dlq_arn" {
  value = aws_sqs_queue.scan_worker_dlq.arn
}
