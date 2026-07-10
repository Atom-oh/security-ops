#!/usr/bin/env bash
# 공용 헬퍼: 슬롯 디렉터리, 스킵 로깅.
set -uo pipefail

# slot 디렉터리 보장 — 비-ephemeral 러너에서 $WORK 가 재사용될 수 있으므로, 이전 실행의
# 셀 파일이 남아 새 실행의 체어 입력에 섞이지 않도록 매번 비우고 새로 만든다. 유일한
# 호출자(run-panel.sh)가 이미 $WORK 빈 문자열을 가드하지만, `rm -rf "$1/slot"`처럼
# 파괴적 경로를 만드는 함수는 precheck.sh 의 원칙대로 자기 안에서도 가드한다.
ensure_slots() {
  [ -n "$1" ] || { echo "ensure_slots: \$1(workdir) must not be empty" >&2; return 1; }
  # TOCTOU 가드 — 비-ephemeral 러너의 고정 $WORK 경로를 다른 잡/프로세스가 심링크로
  # 선점하면 rm -rf 가 realpath 를 따라가 타깃 하위를 삭제할 수 있다.
  [ -L "$1" ] && { echo "ensure_slots: \$1(workdir) is a symlink, refusing" >&2; return 1; }
  [ -L "$1/slot" ] && { echo "ensure_slots: \$1/slot is a symlink, refusing" >&2; return 1; }
  rm -rf "$1/slot"; mkdir -p "$1/slot"
}

# 한 패널 실행 결과를 평가해 responded 에 기록. exit-status-aware(fleet 다른 repo들의
# 표준 수정) — 이전엔 slot 이 non-empty 이기만 하면 응답으로 집계했는데, CLI 가 non-zero
# exit 로 실패하면서도 부분 출력(예: "no findings" 류 그럴듯한 텍스트)을 남기면 그걸
# 정상 응답으로 오집계했다. try_panel() 이 마지막 시도의 exit code 를 "$slot.rc" 에
# 남기고, 여기서 그 값이 정확히 "0"이어야만(부재/공백이면 fail-closed 로 1 취급) 응답으로
# 인정한다.
#   $1 slot 파일 경로, $2 패널 라벨, $3 responded 파일
record_result() {
  local slot="$1" label="$2" responded="$3"
  local rc; rc="$(cat "$slot.rc" 2>/dev/null || echo 1)"
  if [ -s "$slot" ] && [ "$rc" = "0" ]; then
    echo "$label" >> "$responded"
  else
    echo "[skip] $label (exit=$rc)" >&2
    : > "$slot"  # 빈 슬롯 보장
  fi
  rm -f "$slot.rc"
}

# 알려진 크리덴셜 포맷(AWS/GitHub/Slack/OpenAI·Anthropic/Google 키, JWT, PEM, AWS secret/
# session token)만 치환 — `key=value` 제네릭 룰은 **의도적으로 뺀다**. 이 함수는 diff
# *입력* 스크럽(run-panel.sh 와 synthesize.sh 가 직접 호출, 인자 없음 → flush 모드)과 셀
# *출력* 스크럽(`scrub_secrets()` 경유, "redact" 모드) 둘 다에 쓰인다 — 그 제네릭 룰을
# 입력에 그대로 쓰면 8자 이상 아무 값이나 `api_key=`/`token=`/`secret=` 류 변수명과 같이
# 있으면 매치해, 정상 코드의 테스트 fixture·mock 인증값까지 `[REDACTED]`로 치환해 리뷰
# 대상 코드 자체를 훼손한다.
#
# PEM 은 BEGIN 만나는 즉시 치환하지 않고 버퍼링한 뒤, valid END 를 만나야만 그 전체를
# `[REDACTED-PRIVATE-KEY]` 로 치환한다(즉시 치환 방식은 나중에 "가짜 블록"으로 판정돼도
# 이미 출력된 redaction 라인과 삼켜진 라인을 복원할 수 없어 정상 콘텐츠가 사라짐). base64
# 문자 또는 RFC 1421 armor 헤더(`Proc-Type:`/`DEK-Info:` 같은 `Key: Value` 줄, 암호화된
# PEM 이 BEGIN 직후 반드시 넣음)가 아닌 줄을 만나면 "진짜 PEM 이 아니었다"로 판정해
# 버퍼를 원문 그대로 복원한다(base64-only 검증만 하면 암호화된 PEM 의 armor 헤더를
# non-base64 로 오판해 실제 키가 스크럽을 우회함). `^[ +-]?` 앵커는 diff 입력(각 줄이
# `+`/`-`/space 로 시작)에도 적용되도록 — 커밋된 PEM 키는 `+-----BEGIN...`/
# `------BEGIN...`(diff 의 `-` + PEM 자체 5개 대시)/` -----BEGIN...`(공백 접두)로 렌더돼
# 순수 `^-----BEGIN`으로는 못 잡는다.
#
# 미종료(hunk/file 경계 또는 EOF 도달, END 못 찾음) 블록 처리는 mode 에 따라 다르다:
# diff *입력*(mode=flush, 기본값)에서는 원문 그대로 flush — 미종료 블록은 진짜 PEM 인지
# 확정 못 했을 뿐 "가짜"로 확정된 것도 아니고, 이미 PR diff 에 평문으로 존재해 flush 해도
# 새 노출이 아니다. 셀 *출력*(mode=redact, `scrub_secrets()` 경유)에서는 모델이 생성한
# 텍스트라 diff 에 이미 있던 게 아니므로 `[REDACTED-UNTERMINATED-PEM-BLOCK]` 로 유지
# (fail-closed).
#
# END 매치 시 치환 라인은 원래 END 라인의 diff prefix(`+`/`-`/공백)를 보존한다(security-ops
# PR#9 라운드1 리뷰 L2-MAJOR) — bare `[REDACTED-PRIVATE-KEY]` 로만 찍으면 "이 PR 이 키를
# 추가했다(critical) vs 삭제했다(무해)"는 unified-diff 구조 자체가 사라진다. 이미 `skip`
# 상태에서 또 BEGIN 라인을 만나면(중첩/재시작) 먼저 이전 buf 를 mode 규칙대로 flush 하고
# 새 블록을 시작한다 — 안 그러면 `buf = $0 "\n"` 가 이전 버퍼를 덮어써 원문 복원 없이 첫
# 블록이 사라진다(PR#9 라운드1 리뷰 L2-MINOR). invalid-line(가짜 블록 판정) 분기도 mode 를
# 따른다 — redact 모드에서 이 분기가 mode 무관하게 버퍼를 원문 flush 하면, 모델이 생성한
# 셀 출력에 진짜 base64 키 본문을 담은 미종료-처럼-보이는 블록이 있을 때 그 키가 공개 PR
# 코멘트로 그대로 흘러나간다 — redact 모드의 "미종료 = fail-closed" 계약을 깨는 회귀였다
# (PR#9 라운드2 리뷰 L2-MAJOR, diff 대조로 confirmed).
scrub_known_credential_formats() {
  local mode="${1:-flush}"
  awk -v mode="$mode" '
    BEGIN { skip = 0; buf = "" }
    /^(diff --git |--- |\+\+\+ |@@ )/ {
      if (skip) {
        if (mode == "redact") { print "[REDACTED-UNTERMINATED-PEM-BLOCK]" } else { printf "%s", buf }
        skip = 0; buf = ""
      }
      print; next
    }
    /^[ +-]?-----BEGIN [A-Z ]*PRIVATE KEY-----/ {
      if (skip) { if (mode == "redact") { print "[REDACTED-UNTERMINATED-PEM-BLOCK]" } else { printf "%s", buf } }
      skip = 1; buf = $0 "\n"; next
    }
    skip && /^[ +-]?-----END [A-Z ]*PRIVATE KEY-----/ {
      marker = ""; if ($0 ~ /^[ +-]/) marker = substr($0, 1, 1)
      print marker "[REDACTED-PRIVATE-KEY]"; skip = 0; buf = ""; next
    }
    skip {
      content = $0; sub(/^[ +-]/, "", content)
      if (content ~ /^[A-Za-z0-9+\/=]*$/ || content ~ /^[A-Za-z-]+:.*$/) { buf = buf $0 "\n"; next }
      if (mode == "redact") { print "[REDACTED-UNTERMINATED-PEM-BLOCK]" } else { printf "%s", buf }
      skip = 0; buf = ""
    }
    { print }
    END {
      if (skip) {
        if (mode == "redact") { print "[REDACTED-UNTERMINATED-PEM-BLOCK]" } else { printf "%s", buf }
      }
    }
  ' | sed -E \
    -e 's/A(KIA|SIA)[0-9A-Z]{16}/[REDACTED-AWS-KEY]/g' \
    -e 's/gh[pousr]_[A-Za-z0-9]{30,}/[REDACTED-GH-TOKEN]/g' \
    -e 's/github_pat_[A-Za-z0-9_]{30,}/[REDACTED-GH-TOKEN]/g' \
    -e 's/xox[abprs]-[A-Za-z0-9-]{10,}/[REDACTED-SLACK-TOKEN]/g' \
    -e 's/(^|[^A-Za-z0-9_])sk-(proj-|ant-)?[A-Za-z0-9_-]{20,}/\1[REDACTED-API-KEY]/g' \
    -e 's/AIza[0-9A-Za-z_-]{30,}/[REDACTED-GOOGLE-KEY]/g' \
    -e 's/eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}/[REDACTED-JWT]/g' \
    -e 's/((^|[^A-Za-z0-9_])(aws_secret_access_key|aws_session_token)[[:space:]]*[:=][[:space:]]*['"'"'"]?)[A-Za-z0-9/+=]{30,}/\1[REDACTED-AWS-SECRET]/gI'
}

# 마지막 방어선(last line of defense) — 위 특정-포맷 룰에 더해 `key=value` 제네릭 룰까지
# 적용한다. 셀 *출력*(체어에게 넘기는 리뷰 텍스트)에만 쓴다 — 출력은 리뷰 대상 코드가
# 아니라 모델이 생성한 자연어라 일반 변수 대입을 오탐으로 지워도 리뷰 품질 훼손이 없고,
# 오히려 패턴 미매칭 크리덴셜이 우연히 인용된 경우까지 넓게 잡는 게 낫다. "redact" 모드로
# 호출 — 미종료 PEM-모양 블록을 만나면 원문 노출 대신 리댁션 유지(diff *입력* 스크럽의
# "이미 PR 에 평문으로 있다" 논거는 모델이 생성한 출력에는 성립하지 않는다).
scrub_secrets() {
  scrub_known_credential_formats redact | sed -E \
    -e 's/((api[_-]?key|aws_secret_access_key|aws_access_key_id|access[_-]?token|client[_-]?secret|secret|passwd|password|token)['"'"'"]?[[:space:]]*[:=][[:space:]]*['"'"'"])[^'"'"'"]{8,}(['"'"'"])/\1[REDACTED]\3/gI' \
    -e 's/((^|[^A-Za-z0-9_])(api[_-]?key|aws_secret_access_key|aws_access_key_id|access[_-]?token|client[_-]?secret|secret|passwd|password|token)[[:space:]]*[:=][[:space:]]*)[A-Za-z0-9/+_-]{16,}/\1[REDACTED]/gI'
}
