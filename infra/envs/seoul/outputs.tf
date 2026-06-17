output "cloudfront_domain" {
  description = "Public SPA URL host."
  value       = module.web.distribution_domain
}

output "cloudfront_distribution_id" {
  value = module.web.distribution_id
}

output "web_bucket" {
  value = module.web.bucket_name
}

output "user_pool_id" {
  value = module.auth.user_pool_id
}

output "user_pool_client_id" {
  value = module.auth.user_pool_client_id
}

output "cognito_issuer_url" {
  value = module.auth.issuer_url
}

output "ecr_repository_url" {
  value = module.ecr.repository_url
}

output "agentcore_runtime_name" {
  value = module.agentcore.runtime_name
}

output "agentcore_execution_role_arn" {
  value = module.agentcore.execution_role_arn
}
