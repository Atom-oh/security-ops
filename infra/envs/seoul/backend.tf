# State backend.
#
# Default: local state (terraform.tfstate in this dir) — used by ./scripts/deploy.sh.
# For team/remote state, uncomment and configure the S3 backend below, create the bucket +
# lock table out-of-band, then `terraform init -migrate-state`.
#
# terraform {
#   backend "s3" {
#     bucket         = "fsi-mythos-tfstate-<account>"
#     key            = "seoul/terraform.tfstate"
#     region         = "ap-northeast-2"
#     dynamodb_table = "fsi-mythos-tflock"
#     encrypt        = true
#   }
# }
