#!/usr/bin/env bash
# One process per required role. Existing workflows retain their publication gate.
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
. "$DIR/lib.sh"
if [ "${1:-}" = "--prepared" ]; then
  WORK="${2:?Expected prepared work directory}"
  [ ! -L "$WORK" ] && [ ! -L "$WORK/slot" ] || exit 1
  python3 - "$DIR" "$WORK" <<'PY'
import os
from pathlib import Path
import subprocess
import sys
sys.path.insert(0, sys.argv[1])
from role_review import load_plan
plan = load_plan(Path(sys.argv[2]).resolve())
if (plan["head_sha"] != os.environ.get("HEAD_SHA")
        or plan["base_sha"] != os.environ.get("BASE_SHA")
        or subprocess.check_output(["git", "rev-parse", "HEAD"]).decode().strip() != plan["base_sha"]):
    raise ValueError("Prepared scope does not match this review or BASE checkout")
PY
else
  WORK="${3:?Expected diff, lenses directory and work directory}"
  ensure_slots "$WORK"
  python3 "$DIR/prepare_roles.py" --work "$WORK" --prepared-diff "$1"
fi
pids=()
for tag in codex kiro-fable kiro-sol claude-self; do
  python3 "$DIR/run_role.py" --work "$WORK" --tag "$tag" &
  pids+=("$!")
done
for pid in "${pids[@]}"; do
  # Aggregation reports missing/failed roles and cannot award coverage for them.
  wait "$pid" || true
done
status=0
python3 "$DIR/role_review.py" aggregate --work "$WORK" || status=$?
# Exit 2 is a recorded coverage failure: let synthesis publish its FAIL report.
[ "$status" -eq 0 ] || [ "$status" -eq 2 ]
