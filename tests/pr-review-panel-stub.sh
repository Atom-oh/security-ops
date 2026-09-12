#!/usr/bin/env bash
# scripts/pr-review/run-panel.sh 의 Kiro 셀 fail-closed 계약을 스텁으로 핀한다(모델 호출 없음).
# kiro-cli 2.11.1 에서 `--trust-tools=`(빈 값)은 "무툴"이 아니라 무시되는 경고 한 줄로
# 퇴화했다(내장 툴 이름이 fs_read → read 등으로 바뀌며 cwd 안 read 가 기본 신뢰됨). 무툴은
# `tools: []` 에이전트를 `--agent` 로 지정해야만 성립하고(v2 엔진; `--v3` 는 이를 무시함),
# 월간 요청 한도(MONTHLY_REQUEST_COUNT) 소진은 rc=0+빈 stdout 으로 끝나 재시도만 태우므로
# 시그니처 감지가 있어야 원인이 코멘트/로그에 드러난다. 둘 다 조용히 되돌려지는 걸 막는다.
# 이 repo 의 tests/run-all.sh(pytest/vite/terraform 게이트)와는 독립 — 단독 실행:
#   bash tests/pr-review-panel-stub.sh
set -uo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PANEL="$ROOT/scripts/pr-review/run-panel.sh"
SYNTH="$ROOT/scripts/pr-review/synthesize.sh"
AGENT="$ROOT/scripts/pr-review/agents/pr-review-notools.json"

PASS=0; FAIL=0
ok()   { PASS=$((PASS + 1)); echo "  ok   - $1"; }
bad()  { FAIL=$((FAIL + 1)); echo "  FAIL - $1"; [ -n "${2:-}" ] && printf '%s\n' "$2" | sed 's/^/         /' | head -20; }
assert_match()    { if printf '%s' "$3" | grep -qE -- "$2"; then ok "$1"; else bad "$1" "$3"; fi; }
assert_no_match() { if printf '%s' "$3" | grep -qE -- "$2"; then bad "$1" "$3"; else ok "$1"; fi; }
assert_file()     { if [ -f "$2" ]; then ok "$1"; else bad "$1" "missing: $2"; fi; }
assert_no_file()  { if [ -f "$2" ]; then bad "$1" "unexpected: $2"; else ok "$1"; fi; }
assert_eq()       { if [ "$2" = "$3" ]; then ok "$1"; else bad "$1" "expected '$2', got '$3'"; fi; }

echo "== static =="
bash -n "$PANEL" && ok "run-panel.sh valid bash" || bad "run-panel.sh valid bash"
bash -n "$SYNTH" && ok "synthesize.sh valid bash" || bad "synthesize.sh valid bash"
assert_file "kiro no-tools agent config present" "$AGENT"
AGENT_CHECK="$(python3 -c 'import json,sys; d=json.load(open(sys.argv[1])); print(d["name"], len(d["tools"]), len(d["mcpServers"]))' "$AGENT" 2>/dev/null || echo bad)"
assert_eq "agent is pr-review-notools with tools: [] and no mcpServers" "pr-review-notools 0 0" "$AGENT_CHECK"
PANEL_SRC="$(grep -v '^\s*#' "$PANEL")"
assert_match "run-panel.sh passes --agent \"\$KIRO_AGENT_NAME\" to kiro-cli chat" \
  'kiro-cli chat .*--agent "\$KIRO_AGENT_NAME"' "$(printf '%s' "$PANEL_SRC" | tr '\n' ' ')"
assert_match "run-panel.sh copies the agent file into each cell cwd" \
  'cp "\$KIRO_AGENT_SRC" "\$cell_cwd/\.kiro/agents/"' "$PANEL_SRC"
assert_no_match "run-panel.sh no longer relies on --trust-tools= (ignored by kiro-cli 2.11.1)" '\-{2}trust-tools' "$PANEL_SRC"
assert_no_match "run-panel.sh does not pass --mode default (v3-only flag)" '\-{2}mode default' "$PANEL_SRC"
assert_no_match "run-panel.sh does not use the --v3 engine (ignores tools: [])" 'kiro-cli -{2}v3|-{2}agent-engine' "$PANEL_SRC"
assert_match "run-panel.sh detects the Kiro monthly quota signature (v2 stderr)" 'Monthly request limit reached' "$PANEL_SRC"
assert_match "run-panel.sh detects the Kiro monthly quota signature (v3/JSON)" 'MONTHLY_REQUEST_COUNT' "$PANEL_SRC"
assert_match "run-panel.sh detects the --agent fallback signature" 'no agent with name' "$PANEL_SRC"
SYNTH_SRC="$(grep -v '^\s*#' "$SYNTH")"
assert_match "synthesize.sh renders the Kiro quota banner" 'kiro-quota\.flag' "$SYNTH_SRC"
assert_match "synthesize.sh renders the agent-fallback banner" 'kiro-agent-fallback\.flag' "$SYNTH_SRC"
assert_file "runbook for the panel failure modes exists" "$ROOT/docs/runbooks/pr-review-panel.md"

echo "== behaviour (stubbed kiro-cli / codex) =="
T_STUB="$(mktemp -d)"
trap 'rm -rf "$T_STUB"' EXIT
cat > "$T_STUB/codex" <<'EOF'
#!/bin/bash
cat > /dev/null; echo "no findings"
EOF
chmod +x "$T_STUB/codex"
mkdir -p "$T_STUB/lenses" && echo "lens" > "$T_STUB/lenses/L2.txt"
# 이 repo 의 run-panel.sh 는 워크플로가 부여하는 nonce fence 를 검증한다 — 테스트 diff 도 fence.
NONCE="$(python3 -c 'import secrets; print(secrets.token_hex(8))')"
printf '<<<UNTRUSTED_DIFF_%s>>>\ndiff --git a/x b/x\n+x\n<<<END_UNTRUSTED_DIFF_%s>>>\n' "$NONCE" "$NONCE" > "$T_STUB/diff.txt"
run_panel() {
  PATH="$T_STUB:$PATH" PANEL_TIMEOUT=30 PANEL_RETRIES=3 HOME="$T_STUB/home" \
    bash "$PANEL" "$T_STUB/diff.txt" "$T_STUB/lenses" "$T_STUB/work" 2>&1 || true
}
write_kiro() { cat > "$T_STUB/kiro-cli"; chmod +x "$T_STUB/kiro-cli"; }

# (a) v2 한도 소진: rc=0, 빈 stdout, stderr 시그니처 → 재시도 없이 quota 플래그 + severe.
write_kiro <<'EOF'
#!/bin/bash
[ "${1:-}" = "--version" ] && { echo "kiro-cli 2.11.1-stub"; exit 0; }
printf 'Monthly request limit reached\nThe limits reset on 10/01.\n' >&2
exit 0
EOF
OUT="$(run_panel)"
assert_match "version is logged on the first line" '^run-panel.sh: kiro-cli 2.11.1-stub' "$OUT"
assert_match "quota exhaustion logs [quota] per cell" '\[quota\] kiro-opus-L2' "$OUT"
assert_no_match "quota exhaustion is not retried" '\[retry ' "$OUT"
assert_match "quota exhaustion is reported as ::error:: with the reset date" '::error::Kiro monthly request quota exhausted.*reset on 10/01' "$OUT"
assert_file "quota exhaustion leaves kiro-quota.flag" "$T_STUB/work/kiro-quota.flag"
assert_file "quota exhaustion still forces coverage-severe (fail-closed kept)" "$T_STUB/work/coverage-severe.flag"
assert_no_file "quota exhaustion is not an agent fallback" "$T_STUB/work/kiro-agent-fallback.flag"
assert_match "only codex counted" 'Panel responded \(1 / 3 cells\): codex/L2' "$OUT"

# (b) v3 형태(rc=1, 메시지 stdout, JSON stderr) 도 stderr 만으로 잡혀야 한다.
write_kiro <<'EOF'
#!/bin/bash
[ "${1:-}" = "--version" ] && { echo "kiro-cli stub"; exit 0; }
echo "You've reached your monthly usage limit."
echo '[ERROR] [KRS] HTTP 400 body={"__type":"...ServiceQuotaExceededException","reason":"MONTHLY_REQUEST_COUNT"}' >&2
exit 1
EOF
OUT="$(run_panel)"
assert_no_match "v3-style quota error is not retried" '\[retry ' "$OUT"
assert_match "v3-style quota error is reported" '::error::Kiro monthly request quota exhausted' "$OUT"
assert_eq "v3-style quota stdout message is not counted as a response" "0" "$(cat "$T_STUB"/work/slot/kiro-*.md 2>/dev/null | wc -c | tr -d ' ')"

# (c) 에이전트 폴백: stderr 한 줄 + rc=0 + 그럴듯한 응답 → 응답 폐기, fallback 플래그, severe.
write_kiro <<'EOF'
#!/bin/bash
[ "${1:-}" = "--version" ] && { echo "kiro-cli stub"; exit 0; }
echo "Error: no agent with name pr-review-notools found. Falling back to user specified default" >&2
echo "> no findings"
exit 0
EOF
OUT="$(run_panel)"
assert_match "agent fallback logs [agent-fallback] per cell" '\[agent-fallback\] kiro-gpt-L2' "$OUT"
assert_match "agent fallback is reported as ::error::" '::error::kiro-cli ignored --agent pr-review-notools' "$OUT"
assert_no_match "agent-fallback responses are not counted" 'Panel responded.*kiro-' "$OUT"
assert_file "agent fallback leaves kiro-agent-fallback.flag" "$T_STUB/work/kiro-agent-fallback.flag"
assert_file "agent fallback forces coverage-severe" "$T_STUB/work/coverage-severe.flag"
assert_no_file "agent fallback is not a quota failure" "$T_STUB/work/kiro-quota.flag"

# (d) 정상 응답: 플래그 없음, 에이전트 파일이 셀 cwd 에 복사됨, 호출 플래그 계약.
write_kiro <<'EOF'
#!/bin/bash
[ "${1:-}" = "--version" ] && { echo "kiro-cli stub"; exit 0; }
printf '%s\n' "$*" > "$HOME/argv.txt"
[ -f "$HOME/.kiro/agents/pr-review-notools.json" ] && touch "$HOME/agent-seen"
echo "> no findings"
EOF
OUT="$(run_panel)"
assert_match "healthy kiro cells are counted" 'Panel responded \(3 / 3 cells\)' "$OUT"
assert_eq "healthy run leaves no flags" "0" "$(find "$T_STUB/work" -maxdepth 1 -name '*.flag' | wc -l | tr -d ' ')"
assert_eq "previous run's quota/fallback flags were reset" "0" "$(ls "$T_STUB/work"/kiro-quota.flag "$T_STUB/work"/kiro-agent-fallback.flag 2>/dev/null | wc -l | tr -d ' ')"
assert_file "agent file was copied into the cell cwd (HOME)" "$T_STUB/work/kiro-cwd/kiro-opus-L2/agent-seen"
ARGV="$(cat "$T_STUB/work/kiro-cwd/kiro-opus-L2/argv.txt")"
assert_match "cell invocation uses --agent pr-review-notools --no-interactive --wrap never" \
  '--model claude-opus-5 --agent pr-review-notools --no-interactive --wrap never' "$ARGV"
assert_no_match "cell invocation has no --trust-tools / --mode default" 'trust-tools|--mode default' "$ARGV"

# (e) codex 는 stderr 에 입력 diff 를 echo 한다 — Kiro 오류 문구를 인용한 diff 가 codex 셀을 오폐기하면 안 된다.
cat > "$T_STUB/codex" <<'EOF'
#!/bin/bash
cat >&2; echo "no findings"
EOF
printf '<<<UNTRUSTED_DIFF_%s>>>\ndiff --git a/x b/x\n+Monthly request limit reached\n+no agent with name pr-review-notools found\n<<<END_UNTRUSTED_DIFF_%s>>>\n' "$NONCE" "$NONCE" > "$T_STUB/diff.txt"
OUT="$(run_panel)"
assert_match "Codex quoting Kiro errors remains a successful response" 'Panel responded \(3 / 3 cells\)' "$OUT"
assert_eq "quoted Kiro errors in Codex stderr leave no flags" "0" "$(find "$T_STUB/work" -maxdepth 1 -name '*.flag' | wc -l | tr -d ' ')"

# (f) 에이전트 구성 오류(중복 키로 tools 부활)는 모델 호출 전에 거부된다.
mkdir -p "$T_STUB/fixture/agents"
cp "$PANEL" "$T_STUB/fixture/run-panel.sh"; cp "$ROOT/scripts/pr-review/lib.sh" "$T_STUB/fixture/lib.sh"
echo '{"name":"pr-review-notools","tools":[],"tools":["read"],"allowedTools":[],"mcpServers":{},"resources":[],"useLegacyMcpJson":false}' \
  > "$T_STUB/fixture/agents/pr-review-notools.json"
rm -rf "$T_STUB/work"
RC=0; OUT="$(PATH="$T_STUB:$PATH" bash "$T_STUB/fixture/run-panel.sh" "$T_STUB/diff.txt" "$T_STUB/lenses" "$T_STUB/work" 2>&1)" || RC=$?
assert_eq "duplicate JSON keys are rejected before startup (rc=1)" "1" "$RC"
assert_match "invalid agent config is named in the error" 'invalid no-tools agent configuration' "$OUT"
assert_eq "invalid agent configuration never reaches a model" "0" "$(find "$T_STUB/work/kiro-cwd" -name argv.txt 2>/dev/null | wc -l | tr -d ' ')"
rm -f "$T_STUB/fixture/agents/pr-review-notools.json"
RC=0; OUT="$(PATH="$T_STUB:$PATH" bash "$T_STUB/fixture/run-panel.sh" "$T_STUB/diff.txt" "$T_STUB/lenses" "$T_STUB/work" 2>&1)" || RC=$?
assert_eq "missing agent file aborts (rc=1)" "1" "$RC"
assert_match "missing agent file is named in the error" 'kiro no-tools agent config missing' "$OUT"

# (g) synthesize 배너: 플래그 → 코멘트 상단 배너(체어는 스텁 claude 로 대체).
cat > "$T_STUB/claude" <<'EOF'
#!/bin/bash
cat > /dev/null; printf 'ok\n\nVERDICT: PASS\n'
EOF
chmod +x "$T_STUB/claude"
mkdir -p "$T_STUB/swork/slot"; : > "$T_STUB/swork/responded.txt"; echo "codex/L2" > "$T_STUB/swork/responded.txt"
: > "$T_STUB/swork/slot/codex-L2.md"; echo "no findings" > "$T_STUB/swork/slot/codex-L2.md"
printf 'kiro-opus\nkiro-gpt\n' > "$T_STUB/swork/degraded-models.txt"
echo "Monthly request limit reached The limits reset on 10/01." > "$T_STUB/swork/kiro-quota.flag"
echo "Error: no agent with name pr-review-notools found." > "$T_STUB/swork/kiro-agent-fallback.flag"
: > "$T_STUB/swork/coverage-severe.flag"
SOUT="$(cd "$T_STUB" && PATH="$T_STUB:$PATH" bash "$SYNTH" "$T_STUB/diff.txt" "$T_STUB/swork" 1 "stub title" "$T_STUB/review.md" 2>&1 || true)"
REVIEW="$(cat "$T_STUB/review.md" 2>/dev/null)"
assert_match "synthesize renders the quota banner" '🚫 \*\*Kiro 월간 요청 한도 소진\*\*.*reset on 10/01' "$REVIEW"
assert_match "synthesize renders the agent-fallback banner" '🔓 \*\*Kiro 무툴 계약 위반\*\*' "$REVIEW"
assert_match "severe banner still forces FAIL" '커버리지 붕괴로 강제 FAIL' "$REVIEW"
assert_eq "last non-empty line is VERDICT: FAIL" "VERDICT: FAIL" "$(awk 'NF{last=$0} END{print last}' "$T_STUB/review.md" 2>/dev/null)"
[ "$FAIL" -gt 0 ] && [ -z "$REVIEW" ] && printf '%s\n' "$SOUT" | tail -20

echo "== $PASS passed, $FAIL failed =="
[ "$FAIL" -eq 0 ]
