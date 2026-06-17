# Remote state. Configure the bucket/table (created out-of-band) then `terraform init`.
# For local validation, run: terraform init -backend=false
terraform {
  backend "s3" {
    # bucket         = "fsi-mythos-tfstate-<account>"
    # key            = "seoul/terraform.tfstate"
    # region         = "ap-northeast-2"
    # dynamodb_table = "fsi-mythos-tflock"
    # encrypt        = true
  }
}
