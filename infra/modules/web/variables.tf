variable "name_prefix" {
  type    = string
  default = "fsi-mythos"
}

variable "web_acl_arn" {
  type        = string
  description = "WAFv2 WebACL ARN (CLOUDFRONT scope, from us-east-1)."
  default     = null
}

variable "tags" {
  type    = map(string)
  default = {}
}
