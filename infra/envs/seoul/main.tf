provider "aws" {
  region = var.region
}

# CLOUDFRONT-scoped WAF must be created in us-east-1.
provider "aws" {
  alias  = "us_east_1"
  region = "us-east-1"
}

module "data" {
  source     = "../../modules/data"
  table_name = "SCAN_HISTORY"
  tags       = var.tags
}

module "auth" {
  source      = "../../modules/auth"
  name_prefix = var.name_prefix
  tags        = var.tags
}

module "ecr" {
  source    = "../../modules/ecr"
  repo_name = var.name_prefix
  tags      = var.tags
}

module "waf" {
  source      = "../../modules/waf"
  name_prefix = var.name_prefix
  tags        = var.tags
  providers = {
    aws.useast1 = aws.us_east_1
  }
}

module "web" {
  source      = "../../modules/web"
  name_prefix = var.name_prefix
  web_acl_arn = module.waf.web_acl_arn
  tags        = var.tags
}

module "agentcore" {
  source             = "../../modules/agentcore"
  name_prefix        = var.runtime_name
  region             = var.region
  image_uri          = var.image_uri
  image_digest       = var.image_digest
  dynamodb_table_arn = module.data.table_arn
  ecr_repository_arn = module.ecr.repository_arn
  model_arns         = var.model_arns
  cognito_issuer_url = module.auth.issuer_url
  cognito_client_id  = module.auth.user_pool_client_id
  tags               = var.tags
}
