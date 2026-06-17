data "aws_region" "current" {}

# Email-alias pool: users sign in with email; Username is an opaque UUID.
resource "aws_cognito_user_pool" "this" {
  name                     = "${var.name_prefix}-pool"
  username_attributes      = ["email"]
  auto_verified_attributes = ["email"]

  password_policy {
    minimum_length    = 12
    require_lowercase = true
    require_uppercase = true
    require_numbers   = true
    require_symbols   = true
  }

  admin_create_user_config {
    allow_admin_create_user_only = true
  }

  tags = var.tags
}

# Public SPA client — no secret, SRP auth flow.
resource "aws_cognito_user_pool_client" "this" {
  name         = "${var.name_prefix}-spa"
  user_pool_id = aws_cognito_user_pool.this.id

  generate_secret = false
  explicit_auth_flows = [
    "ALLOW_USER_SRP_AUTH",
    "ALLOW_REFRESH_TOKEN_AUTH",
  ]

  callback_urls                        = var.callback_urls
  supported_identity_providers         = ["COGNITO"]
  allowed_oauth_flows_user_pool_client = false

  access_token_validity  = 60
  id_token_validity      = 60
  refresh_token_validity = 30
  token_validity_units {
    access_token  = "minutes"
    id_token      = "minutes"
    refresh_token = "days"
  }
}

resource "aws_cognito_user_pool_domain" "this" {
  # Cognito domains must be lowercase and free of underscores; the pool id carries both.
  domain       = replace(lower("${var.name_prefix}-${aws_cognito_user_pool.this.id}"), "_", "-")
  user_pool_id = aws_cognito_user_pool.this.id
}
