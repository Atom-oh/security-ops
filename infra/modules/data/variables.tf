variable "table_name" {
  type        = string
  description = "Scan-history DynamoDB table name."
  default     = "SCAN_HISTORY"
}

variable "tags" {
  type    = map(string)
  default = {}
}
