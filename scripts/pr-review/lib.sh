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
# 경우)이며, 셀 출력을 체어에 넘기기 전에 흔한 크리덴셜 포맷을 정규식으로 치환한다. 패턴은 co-agent 의
# `consensus_hooks.py::_SECRET_RE`(AWS/GitHub/Slack/OpenAI·Anthropic/Google + generic
# key=value)를 재사용하고, EKS Pod Identity 토큰(고정 경로 파일의 값 자체가 JWT 포맷)
# 탐지를 추가했다. Kiro 의 절대경로 read 경로 자체는 위 tool-grant 제거로 이미 구조적으로
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
# 일반 변수 대입은 건드리지 않는다.
scrub_known_credential_formats() {
  # PEM 은 여러 줄에 걸치므로 line-oriented sed 로는 본문을 못 지운다(헤더 줄만 매칭)
  # — awk 상태기계로 BEGIN..END 블록 전체를 마커 한 줄로 치환(첫 스테이지, 구조적 스크럽).
  awk '
    BEGIN { skip = 0 }
    /^-----BEGIN [A-Z ]*PRIVATE KEY-----/ { print "[REDACTED-PRIVATE-KEY]"; skip = 1; next }
    skip && /^-----END [A-Z ]*PRIVATE KEY-----/ { skip = 0; next }
    skip { next }
    { print }
    END { if (skip) print "[REDACTED-UNTERMINATED-PEM-BLOCK]" }
  ' | sed -E \
    -e 's/A(KIA|SIA)[0-9A-Z]{16}/[REDACTED-AWS-KEY]/g' \
    -e 's/gh[pousr]_[A-Za-z0-9]{30,}/[REDACTED-GH-TOKEN]/g' \
    -e 's/github_pat_[A-Za-z0-9_]{30,}/[REDACTED-GH-TOKEN]/g' \
    -e 's/xox[abprs]-[A-Za-z0-9-]{10,}/[REDACTED-SLACK-TOKEN]/g' \
    -e 's/(^|[^A-Za-z0-9_])sk-(proj-|ant-)?[A-Za-z0-9_-]{20,}/\1[REDACTED-API-KEY]/g' \
    -e 's/AIza[0-9A-Za-z_-]{30,}/[REDACTED-GOOGLE-KEY]/g' \
    -e 's/eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}/[REDACTED-JWT]/g'
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
