variable "table_name" {
  type        = string
  description = "Scan-history DynamoDB table name."
  default     = "SCAN_HISTORY"
}

variable "tags" {
  type    = map(string)
  default = {}
}

variable "scan_visibility_timeout_seconds" {
  description = "SQS visibility timeout for the scan-worker queue; must exceed the worst-case scan duration."
  type        = number
  default     = 2400 # 40 min
}

variable "scan_max_receive_count" {
  description = "Deliveries before a scan message is sent to the DLQ."
  type        = number
  default     = 3
}
