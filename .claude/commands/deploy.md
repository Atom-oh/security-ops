Deploy to Seoul (ap-northeast-2). Confirm the target AWS account before applying.
- Full: `AWS_REGION=ap-northeast-2 ./scripts/deploy.sh`
- Backend only: `./scripts/build_push_backend.sh` (rebuild ARM64 → ECR → update-agent-runtime)
- Frontend only: `./scripts/build_frontend.sh` (vite build → S3 sync → CloudFront invalidation)
After deploy, verify the runtime is READY and the SPA loads.
