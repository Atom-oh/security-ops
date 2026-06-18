#!/usr/bin/env bash
# PreToolUse (opt-in): warn on likely secrets in a write payload. Reads $CLAUDE_TOOL_INPUT.
# Advisory by default (exit 0). To hard-block, change the exit code to 2.
in="${CLAUDE_TOOL_INPUT:-}"
if printf '%s' "$in" | grep -EqI 'AKIA[0-9A-Z]{16}|-----BEGIN [A-Z ]*PRIVATE KEY-----|(secret|password|api[_-]?key|token)\s*[:=]\s*["'"'"'][^"'"'"']{12,}'; then
  echo "⚠️ secret-scan: a possible hardcoded secret was detected in the payload." >&2
fi
exit 0
