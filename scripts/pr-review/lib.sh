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

# 한 패널 실행 결과를 평가해 responded 에 기록. $1.rc(run-panel.sh 의 try_panel() 이 마지막
# 시도의 exit code 를 남긴 sidecar 파일)를 읽어 slot 이 non-empty 라도 rc != 0 이면 실패로
# 처리하고, 처리 후 그 sidecar 파일은 지운다(side effect).
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

# 자격증명 패턴 스크럽 — 마지막 방어선(last line of defense), 예방이 아님. Kiro fs_read
# 잔여 위험은 그 tool grant 자체를 제거해 구조적으로 닫혔다(이 수정을 다룬 원본 ADR은
# oh-my-cloud-skills 저장소의 ADR-013 — 이 repo 자신의 ADR 번호와는 무관) — 이 스크럽은
# 이제 일반적인 defense-in-depth(다른 경로로 우연히 크리덴셜성 값이 셀 출력에 섞여 나오는
# 경우)이며, 셀 출력을 체어에 넘기기 전에 흔한 크리덴셜 포맷을 정규식으로 치환한다. **패턴은
# co-agent 의 `consensus_hooks.py::_SECRET_RE`(AWS/GitHub/Slack/OpenAI·Anthropic/Google +
# generic key=value)를 재사용한다 — 이 "generic key=value" 는 아래 `scrub_secrets()`
# (셀 출력 스크럽) 에만 적용되고, diff *입력* 스크럽용 `scrub_known_credential_formats()`
# 는 그 generic 룰을 의도적으로 뺀 부분집합이다(round 11 리뷰 MINOR — 이 문단이
# `scrub_known_credential_formats()` 정의 바로 위에 있어 "이 함수도 generic 룰을
# 포함한다"고 오독될 수 있었던 것을 명확화).** EKS Pod Identity 토큰(고정 경로 파일의
# 값 자체가 JWT 포맷) 탐지를 추가했다. Kiro 의 절대경로 read 경로 자체는 위 tool-grant
# 제거로 이미 구조적으로
# 닫혔으므로(더 이상 residual 위험이 아님) — 이 스크럽이 실제로 잡는 잔여 케이스는 그와
# 무관한 다른 경로들뿐이다: 실수로 diff 에 커밋된 시크릿이 셀 출력에 그대로 인용되는
# 경우, codex/claude-self 등 다른 패널원의 stderr/출력에 크리덴셜성 값이 우연히 섞이는
# 경우 등(security-ops PR #7 리뷰 MAJOR — 이 문단의 이전 버전이 "절대경로 read 잔여
# 위험은 그대로 남는다"고 서술해 위 문장과 자기모순이었고, 당시 이 repo에 존재하지 않던
# ADR 번호를 잘못 인용했던 것을 수정. 이 repo의 실제 ADR-002는 완전히 다른 주제
# — Kiro diff truncation 을 advisory 로 둔 정책 결정 — 이므로 혼동하지 말 것).
# 알려진 크리덴셜 포맷(AWS/GitHub/Slack/OpenAI·Anthropic/Google 키, JWT, PEM)만 치환 —
# `key=value` 제네릭 룰은 **의도적으로 뺀다**. 리뷰 *입력*(diff)에 적용할 목적으로 분리:
# 그 제네릭 룰은 8자 이상 아무 값이나 `api_key=`/`token=`/`secret=` 류 변수명과 함께
# 있으면 매치하므로, 정상 코드의 테스트 fixture·mock 인증값·config 기본값까지
# `[REDACTED]`로 치환해 리뷰 대상 코드 자체를 훼손한다(security-ops PR #7 리뷰 round 9
# MAJOR — codex·kiro-gpt 2벤더 독립 수렴: scrub_secrets()를 diff 입력에 그대로 썼다가
# 벤더 둘 다 redacted 코드를 리뷰하게 됨). 알려진 실제 크리덴셜 포맷은 여전히 잡되,
# 일반 변수 대입은 건드리지 않는다. 단, AWS secret access key/session token 은
# 자체 인식 가능한 접두사가 없어(access key ID 만 `AKIA`/`ASIA` 접두 — 위 첫 룰)
# 순수 포맷 기반으로는 못 잡는 진짜 gap 이었다(round 10 리뷰 L3 MAJOR). 변수명을
# `aws_secret_access_key`/`aws_session_token` **정확히 그 둘로만** 좁히고 값 길이도
# 30자 이상으로 게이트해, 일반 test fixture(보통 짧고 변수명도 다름)를 계속 피하면서
# 그 두 실제 AWS 크리덴셜 종류는 잡는다 — 완전한 해결은 아니다(다른 이름의 변수에
# 담긴 시크릿은 여전히 통과), 남은 residual 은 이 스크럽이 last-line-of-defense 이지
# 예방이 아니라는 파일 상단 원칙을 그대로 따른다. **명시적 전제(round 11 리뷰 L3
# MAJOR 요청 — single-tenant 러너 전제를 코드에 문서화)**: 이 스크립트가 이 diff를
# argv 로 embed 하는 것(Kiro 셀)과 stdin 파일로 넘기는 것(codex 셀)은 둘 다 이 CI
# 잡을 실행하는 self-hosted 러너가 **single-tenant**(동시에 다른 사용자/잡의 프로세스가
# `ps`/`/proc/<pid>/cmdline` 을 관찰할 수 없음)라는 전제 위에 있다 — 이는 fs_read
# CRITICAL(diff-injection → 임의 파일 read)을 닫기 위해 채택한 의도된 트레이드오프이며,
# 이 스크립트만으로 강제할 수 없는 배포 환경의 속성이다. 러너가 multi-tenant 로
# 바뀌면 이 전제가 깨지고 재검토가 필요하다.
scrub_known_credential_formats() {
  # PEM 은 여러 줄에 걸치므로 line-oriented sed 로는 본문을 못 지운다(헤더 줄만 매칭)
  # — awk 상태기계로 BEGIN..END 블록 전체를 마커 한 줄로 치환(첫 스테이지, 구조적 스크럽).
  # `^[ +-]?` — 이 함수는 이제 diff 입력(각 줄이 `+`/`-`/space 로 시작)에도 적용되는데,
  # 원래 앵커(`^-----BEGIN`)는 unified diff 의 커밋된 PEM 키를 못 잡는다: 추가된 줄은
  # `+-----BEGIN...`, 삭제된 줄은 `------BEGIN...`(diff 의 `-` + PEM 자체 5개 대시),
  # context 줄은 ` -----BEGIN...`(공백 접두)로 렌더돼 어느 것도 `^-----`에 매치 안 됨
  # (round 12 리뷰 L2 MAJOR — diff 대조로 CONFIRMED, sed 규칙들은 앵커가 없어 이 결함이
  # 없었다). optional 문자 클래스 하나로 네 가지 경우(무접두/공백/plus/minus) 모두 커버.
  # hunk/file 경계·EOF 에서도 buf 를 원문 그대로 flush(round 16 리뷰 MAJOR — round 13/15
  # 는 여기서 `[REDACTED-UNTERMINATED-PEM-BLOCK]` 를 찍고 buf 를 버렸는데, 이는 mid-stream
  # 에서 non-base64 라인을 만났을 때 buf 를 복원하는 동작과 **비대칭**이었다: 결과적으로
  # "END 를 못 찾은 채 경계/EOF 에 닿은 경우"만 정상 diff 내용을 아무 신호 없이 삭제하는
  # 코드였다(다벤더 독립 수렴 CONFIRMED). 미종료 블록은 진짜 PEM 인지 끝까지 확인 못했다는
  # 뜻일 뿐 "가짜"라고 확정된 것도 아니므로, 판정 불능 상태에서는 데이터를 지우기보다
  # 그대로 보존하는 쪽이 이 스크립트의 우선순위(coverage > redaction, last-line-of-defense
  # 는 예방이 아니라는 파일 상단 원칙)에 맞다 — 실제로 여기서 잘리는 것이 진짜 키일 확률은
  # 극히 낮고(멀티-hunk 파일에서 키 본문이 정확히 hunk 경계에서 쪼개져야 함), 설령 잘려도
  # 그 diff 는 이미 PR 자체에 평문으로 존재해 리뷰어들에게 새로운 노출이 아니다.
  # BEGIN 후 즉시 치환하지 않고 버퍼링(round 15 리뷰 — round 14 의 base64 검증이 두
  # 갈래로 잘못됐던 것을 근본 수정): (1) BEGIN 라인을 만나는 즉시 `[REDACTED-...]`를
  # 출력해버리면, 나중에 non-base64 라인으로 "가짜 블록"이라 판정해도 이미 출력된
  # redaction 라인과 그 사이 삼켜진 라인들을 복원할 수 없어 정상 diff 내용이 그냥
  # 사라졌다(false-positive 취소 시 라인 소실, MAJOR). (2) base64 전용 검증은 RFC 1421
  # armor 헤더(`Proc-Type:`/`DEK-Info:` 같은 `Key: Value` 줄, 암호화된 PEM 이 BEGIN
  # 직후 반드시 넣는 줄)를 non-base64 로 오판해, **실제 암호화 private key** 가 스크럽을
  # 그대로 우회해 codex/Kiro/chair 를 거쳐 공개 코멘트까지 흐를 수 있었다(false-negative,
  # MAJOR — 이 스크럽이 막으려는 바로 그 케이스). 이제 BEGIN 부터의 후보 블록 전체를
  # `buf` 에 모으고, valid END 를 만나야만 그 전체를 `[REDACTED-PRIVATE-KEY]` 한 줄로
  # 치환·출력한다. base64 도 armor 헤더(`Key: Value`)도 아닌 줄을 만나거나 hunk/file
  # 경계·EOF 에 닿으면 "확정 못함"으로 판단해 버퍼를 원문 그대로 flush(위 세 종료 경로
  # 모두 동일하게 처리 — 비대칭 없음).
  awk '
    BEGIN { skip = 0; buf = "" }
    /^(diff --git |--- |\+\+\+ |@@ )/ {
      if (skip) { printf "%s", buf; skip = 0; buf = "" }
      print; next
    }
    /^[ +-]?-----BEGIN [A-Z ]*PRIVATE KEY-----/ { skip = 1; buf = $0 "\n"; next }
    skip && /^[ +-]?-----END [A-Z ]*PRIVATE KEY-----/ { print "[REDACTED-PRIVATE-KEY]"; skip = 0; buf = ""; next }
    skip {
      content = $0; sub(/^[ +-]/, "", content)
      if (content ~ /^[A-Za-z0-9+\/=]*$/ || content ~ /^[A-Za-z-]+:.*$/) { buf = buf $0 "\n"; next }
      # base64 도 armor 헤더도 아님 — 진짜 PEM 이 아니라고 판단, 버퍼를 원문 그대로
      # 복원(false positive 취소). next 를 호출하지 않아 아래 무조건 { print } 로
      # 이어져 이번 줄도 정상 출력된다.
      printf "%s", buf; skip = 0; buf = ""
    }
    { print }
    END { if (skip) printf "%s", buf }
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
# 적용한다. 이건 셀 *출력*(체어에게 넘기는 리뷰 텍스트)에만 쓴다 — 출력은 리뷰 대상
# 코드가 아니라 모델이 생성한 자연어이므로, 일반 변수 대입을 오탐으로 지워도 리뷰
# 품질 훼손이 없고, 오히려 패턴 미매칭 크리덴셜이 우연히 인용된 경우까지 넓게 잡는 게
# 낫다.
scrub_secrets() {
  scrub_known_credential_formats | sed -E \
    -e 's/((api[_-]?key|aws_secret_access_key|aws_access_key_id|access[_-]?token|client[_-]?secret|secret|passwd|password|token)['"'"'"]?[[:space:]]*[:=][[:space:]]*['"'"'"])[^'"'"'"]{8,}(['"'"'"])/\1[REDACTED]\3/gI' \
    -e 's/((^|[^A-Za-z0-9_])(api[_-]?key|aws_secret_access_key|aws_access_key_id|access[_-]?token|client[_-]?secret|secret|passwd|password|token)[[:space:]]*[:=][[:space:]]*)[A-Za-z0-9/+_-]{16,}/\1[REDACTED]/gI'
}
