// Runtime configuration from Vite env (VITE_*). Filled from Terraform outputs.
export const config = {
  region: import.meta.env.VITE_REGION ?? "ap-northeast-2",
  userPoolId: import.meta.env.VITE_USER_POOL_ID ?? "",
  userPoolClientId: import.meta.env.VITE_USER_POOL_CLIENT_ID ?? "",
  runtimeArn: import.meta.env.VITE_RUNTIME_ARN ?? "",
};
