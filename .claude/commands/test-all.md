Run the full verification gate and report results:
- `cd backend && pytest`
- `cd frontend && npm run build`
- `cd infra/envs/seoul && terraform init -backend=false && terraform validate`
- or `bash tests/run-all.sh`
Summarize pass/fail with the failing output; do not claim success without the command output.
