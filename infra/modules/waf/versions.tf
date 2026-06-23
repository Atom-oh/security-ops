terraform {
  required_version = ">= 1.5.0"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.60"
      # CLOUDFRONT-scoped WAF must live in us-east-1; the caller passes that provider.
      configuration_aliases = [aws.useast1]
    }
  }
}
