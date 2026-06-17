#!/usr/bin/env bash
# Aggregate verification gate for FSI-Mythos.
# Runs whatever is present: backend pytest, frontend build, terraform validate.
# Designed to degrade gracefully when a stack is not yet scaffolded.
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
rc=0

echo "== backend pytest =="
if [ -d "$ROOT/backend" ] && command -v pytest >/dev/null 2>&1; then
  ( cd "$ROOT/backend" && pytest )
  prc=$?
  # exit 5 = "no tests collected" — fine before any tests exist.
  if [ "$prc" -ne 0 ] && [ "$prc" -ne 5 ]; then rc=1; fi
else
  echo "  (skipped — no backend/ or pytest)"
fi

echo "== frontend build =="
if [ -f "$ROOT/frontend/package.json" ]; then
  ( cd "$ROOT/frontend" && npm run build --if-present ) || rc=1
else
  echo "  (skipped — no frontend/package.json)"
fi

echo "== terraform validate (seoul) =="
if [ -d "$ROOT/infra/envs/seoul" ] && command -v terraform >/dev/null 2>&1; then
  ( cd "$ROOT/infra/envs/seoul" && terraform fmt -check -recursive "$ROOT/infra" \
      && terraform init -backend=false -input=false >/dev/null && terraform validate ) || rc=1
else
  echo "  (skipped — no infra/envs/seoul or terraform)"
fi

[ "$rc" -eq 0 ] && echo "ALL GATES PASSED" || echo "SOME GATES FAILED"
exit "$rc"
