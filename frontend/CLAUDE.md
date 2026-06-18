# frontend/ — React + Vite SPA

The single-page UI. Browser calls the AgentCore Runtime `/invocations` directly with the Cognito
access token (Bearer); CloudFront+OAC serves the static build from private S3.

## Layout
- `src/auth/` — Cognito SRP login (`cognito.ts` proactively refreshes near-expiry tokens), `AuthContext`.
- `src/api/agentcore.ts` — bearer call to the runtime; actions scan/scan_async/getScan/listHistory. `types.ts` mirrors backend shapes.
- `src/pages/` — `LoginPage`, `ScanPage` (form + sync/async + polling), `HistoryPage`, `ResultView`.
- `src/components/` — `ScanForm` (source, max_files, pass@k, per-role + ensemble model select, sandbox/ensemble toggles), `PipelineProgress` (live per-phase detail), `FindingsTable` (severity/verdict badge pills, expandable detail), `ScanSummary`, `CicdGate`, `Header`, `Sidebar`, `Shell`.
- `src/styles/` — paper+ink+Claude-orange CSS-variable tokens (`colors`/`typography`/`spacing`/`base`). No Tailwind.

## Rules
- Render each result section only when its data is actually present (IN_PROGRESS records persist empty `{}` — guard against `.length` on undefined).
- `.env` (gitignored) holds VITE_REGION / VITE_USER_POOL_ID / VITE_USER_POOL_CLIENT_ID / VITE_RUNTIME_ARN; `build_frontend.sh` generates it from Terraform outputs.
- Folder upload sends code files only (js/ts/py/java/cpp/c/go), capped by count + bytes.

## Commands
```bash
cd frontend && npm ci && npm run build   # typecheck + vite build
