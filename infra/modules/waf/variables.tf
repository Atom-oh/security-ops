variable "name_prefix" {
  type    = string
  default = "fsi-mythos"
}

variable "rate_limit" {
  type        = number
  description = "Requests per 5-minute window per IP before blocking."
  default     = 2000
}

variable "tags" {
  type    = map(string)
  default = {}
}
