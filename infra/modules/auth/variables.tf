variable "name_prefix" {
  type    = string
  default = "fsi-mythos"
}

variable "callback_urls" {
  type        = list(string)
  description = "Allowed OAuth callback URLs (the CloudFront domain)."
  default     = []
}

variable "tags" {
  type    = map(string)
  default = {}
}
