output "execution_role_arn" {
  value = aws_iam_role.exec.arn
}

# The runtime ARN is produced by the CLI seam, not Terraform state. After apply, read it via:
#   aws bedrock-agentcore-control list-agent-runtimes --region <r> \
#     --query "agentRuntimes[?agentRuntimeName=='<name>'].agentRuntimeArn | [0]"
output "runtime_name" {
  value = var.name_prefix
}
