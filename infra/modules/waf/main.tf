resource "aws_wafv2_web_acl" "this" {
  provider    = aws.useast1
  name        = "${var.name_prefix}-cf-acl"
  description = "FSI-Mythos CloudFront protection"
  scope       = "CLOUDFRONT"

  default_action {
    allow {}
  }

  # AWS managed common rule set.
  rule {
    name     = "AWSManagedCommon"
    priority = 1
    override_action {
      none {}
    }
    statement {
      managed_rule_group_statement {
        name        = "AWSManagedRulesCommonRuleSet"
        vendor_name = "AWS"
      }
    }
    visibility_config {
      cloudwatch_metrics_enabled = true
      metric_name                = "${var.name_prefix}-common"
      sampled_requests_enabled   = true
    }
  }

  # Known-bad inputs.
  rule {
    name     = "AWSManagedBadInputs"
    priority = 2
    override_action {
      none {}
    }
    statement {
      managed_rule_group_statement {
        name        = "AWSManagedRulesKnownBadInputsRuleSet"
        vendor_name = "AWS"
      }
    }
    visibility_config {
      cloudwatch_metrics_enabled = true
      metric_name                = "${var.name_prefix}-badinputs"
      sampled_requests_enabled   = true
    }
  }

  # Per-IP rate limit.
  rule {
    name     = "RateLimit"
    priority = 3
    action {
      block {}
    }
    statement {
      rate_based_statement {
        limit              = var.rate_limit
        aggregate_key_type = "IP"
      }
    }
    visibility_config {
      cloudwatch_metrics_enabled = true
      metric_name                = "${var.name_prefix}-ratelimit"
      sampled_requests_enabled   = true
    }
  }

  visibility_config {
    cloudwatch_metrics_enabled = true
    metric_name                = "${var.name_prefix}-acl"
    sampled_requests_enabled   = true
  }

  tags = var.tags
}
