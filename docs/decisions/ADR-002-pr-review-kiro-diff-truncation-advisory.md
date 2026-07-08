# ADR-002: PR-Review Kiro Diff Truncation — Advisory Banner, Not Forced FAIL

<a href="#english"><img src="https://img.shields.io/badge/lang-English-blue.svg" alt="English"></a>
<a href="#korean"><img src="https://img.shields.io/badge/lang-한국어-red.svg" alt="Korean"></a>

---

<a id="english"></a>

# English

## Status

Accepted (2026-07-08)

> This decision was raised as a MAJOR finding by PR #7's own review panel across two review
> rounds (multiple models, independently, converged on "truncation should force FAIL or chunk
> the diff"). The panel's own suggestion — that keeping this advisory rather than fail-closed
> "cannot be overridden by a code comment alone" without a real decision record — is why this
> ADR exists: the trade-off below was a genuine user-confirmed policy call, not an oversight,
> and belongs here rather than only in an inline comment.

## Context

`scripts/pr-review/run-panel.sh` embeds the PR diff directly into each Kiro cell's `chat`
argument (ADR context: this replaced an `fs_read` tool grant that let a diff-borne prompt
injection read arbitrary files — see the fix commit history on
`fix/pr-review-kiro-fsread-severity-exit`). Process argv has a kernel limit
(`MAX_ARG_STRLEN`, ~128KiB), so large diffs are capped via `KIRO_DIFF_CAP` (default
100000B) — anything beyond that is truncated with a `[...TRUNCATED at ${KIRO_DIFF_CAP}B -- full diff not sent to Kiro...]` marker, and
`run-panel.sh` sets `$WORK/kiro-diff-truncated.flag`.

Codex, by contrast, receives the diff via stdin with no cap — it always sees the full
`$DIFF` this script was invoked with. So a truncated Kiro cell does not mean the PR goes
fully unreviewed past the cap: it means the *Kiro vendor family* only cross-checks the diff
prefix for that PR, while codex still covers the tail.

The question raised repeatedly by review panels (this repo's own PR #7, and independently by
every sibling repo running the same ported lens×model matrix design — oh-my-cloud-skills,
multi-region-architecture, aws-fsi-demo, ttobak, claude-code-usage-dashboard,
AWS-Demo-Platform): should `kiro-diff-truncated.flag` also set `coverage-severe.flag` (i.e.
force `VERDICT: FAIL`), matching this platform's general fail-closed / incomplete-coverage
posture? Or should it remain advisory-only — visible as a banner in the synthesized review,
but not blocking?

## Decision

**Advisory-only. Truncation does not force `VERDICT: FAIL`.**

Reasoning, in the order it was actually weighed:

1. **Not a full coverage collapse.** Truncation degrades one vendor family's (Kiro's)
   coverage of the diff tail to zero; it does not remove all cross-vendor checking the way
   `coverage-severe.flag`'s other trigger (codex dead, or all of Kiro dead) does. Codex still
   reviews the full `$DIFF` this script was invoked with every time, for every lens,
   regardless of the Kiro cap — that input may itself be a workflow-level truncation of the
   raw PR diff (a separate, already-signaled concern upstream of this script), but within
   what this script receives, codex has no cap of its own.
2. **Blast radius of the alternative.** Forcing `FAIL` on truncation would silently widen
   what "review-blocking" means: any sufficiently large PR (a refactor, a vendored dependency
   bump, a generated-code commit) would now fail-closed on the *Kiro leg* even when nothing
   about the change itself is risky. That is a policy change to the gate's scope, not a
   defect fix — it should not happen without an explicit decision, which is what this ADR
   records.
3. **The gate already has an orthogonal, narrower severity axis for real coverage loss.**
   `coverage-severe.flag` is set independently by (a) a vendor family being fully dead
   (`CODEX_DEAD || KIRO_ALL_DEAD`) and (b) a single lens losing an entire vendor family's
   response (`lens-coverage-gap.txt`). Both are genuine "no cross-check happened" cases.
   Truncation is not — it is "one vendor's cross-check saw less of the diff," a strictly
   weaker condition.

This was confirmed as the intended design via an explicit user decision (2026-07-08, in
response to the exact same question raised while fixing the sibling repos sharing this CI
design) — see the "advisory (recommended)" option chosen over "make the gate stricter." That
decision applies across this whole fleet of repos, not just this one.

## Consequences

- A PR whose diff exceeds `KIRO_DIFF_CAP` gets a visible `✂️ **Kiro diff truncated**` banner
  in the synthesized review, but the gate does not block on that alone.
- Reviewers reading the synthesized comment must notice the banner themselves — it is a
  signal, not an enforcement mechanism. If a future incident shows this signal is routinely
  ignored, that is grounds to revisit this ADR (superseding it, not editing it in place).
- Does not preclude *raising* `KIRO_DIFF_CAP` (already user-overridable, validated and
  kernel-limit-clamped) if truncation turns out to be hit often in practice — that is an
  orthogonal, non-blocking mitigation already available.

## References

- `scripts/pr-review/run-panel.sh` (`KIRO_DIFF_CAP`, `kiro-diff-truncated.flag`,
  `coverage-severe.flag`)
- `scripts/pr-review/synthesize.sh` (truncation banner)
- PR #7 review rounds (the MAJOR finding this ADR formalizes the response to)
- Sibling repos' identical trade-off, same user decision: oh-my-cloud-skills, ttobak,
  claude-code-usage-dashboard, multi-region-architecture, aws-fsi-demo, AWS-Demo-Platform

---

<a id="korean"></a>

# 한국어

## 상태

승인됨 (2026-07-08)

> 이 결정은 PR #7 자신의 리뷰 패널이 두 라운드에 걸쳐 MAJOR로 제기했다(여러 모델이
> 독립적으로 "truncation 시 강제 FAIL 하거나 diff 를 chunking 해야 한다"에 도달). 패널
> 자신의 제안 — advisory 유지가 fail-closed 계약과 tension 이 있다면 "코드 주석만으로
> override 할 수 없고" 실제 결정 문서가 필요하다는 지적 — 이 이 ADR이 존재하는 이유다:
> 아래 트레이드오프는 실제 사용자 확인 정책 결정이었고 누락이 아니었으며, 인라인 주석이
> 아니라 여기 남아야 한다.

## 배경

`scripts/pr-review/run-panel.sh`는 PR diff 를 각 Kiro 셀의 `chat` 인자에 직접 embed
한다(맥락: 이는 diff-borne 프롬프트 인젝션이 임의 파일을 읽게 하던 `fs_read` 툴 그랜트를
대체한 것이다 — `fix/pr-review-kiro-fsread-severity-exit` 브랜치의 수정 커밋 히스토리
참조). 프로세스 argv 에는 커널 한도(`MAX_ARG_STRLEN`, ~128KiB)가 있어 대형 diff 는
`KIRO_DIFF_CAP`(기본 100000B)으로 캡핑된다 — 그 이상은 `[...TRUNCATED at ${KIRO_DIFF_CAP}B -- full diff not sent to Kiro...]` 마커로
잘리고, `run-panel.sh`가 `$WORK/kiro-diff-truncated.flag`를 세운다.

반대로 codex 는 diff 를 stdin 으로 받아 캡이 없다 — 이 스크립트가 호출된 `$DIFF` 전체를
항상 본다. 즉 Kiro 셀이 truncated 됐다고 해서 그 PR 이 캡을 넘긴 뒤로 아예 리뷰가 안
되는 게 아니다: 그 PR 에 한해 *Kiro 벤더 패밀리*만 diff prefix 까지만 교차확인하고,
codex 는 여전히 tail 을 커버한다.

같은 포팅된 lens×model 매트릭스 설계를 쓰는 리뷰 패널들이 반복적으로 제기한 질문(이
repo 자신의 PR #7뿐 아니라, oh-my-cloud-skills·multi-region-architecture·aws-fsi-demo·
ttobak·claude-code-usage-dashboard·AWS-Demo-Platform 모든 sibling repo에서 독립적으로):
`kiro-diff-truncated.flag`도 `coverage-severe.flag`를 세워(즉 `VERDICT: FAIL` 강제) 이
플랫폼의 일반적인 fail-closed/incomplete-coverage 원칙과 맞춰야 하는가? 아니면 종합
리뷰의 배너로만 노출되고 게이트를 막지는 않는 advisory-only 로 남아야 하는가?

## 결정

**advisory-only 유지. Truncation 은 `VERDICT: FAIL`을 강제하지 않는다.**

실제로 검토된 순서대로:

1. **완전한 커버리지 붕괴가 아님.** Truncation 은 한 벤더 패밀리(Kiro)의 diff tail
   커버리지만 0으로 낮춘다 — `coverage-severe.flag`의 다른 트리거(codex 전멸, 또는
   kiro 전멸)처럼 모든 교차확인을 없애는 게 아니다. codex 는 Kiro 캡과 무관하게 매번
   모든 lens 에서 이 스크립트가 호출된 `$DIFF` 입력 전체를 리뷰한다 — 그 입력 자체가
   워크플로 단계에서 이미 원본 PR diff 를 선절단한 결과일 수 있으나(이 스크립트 상류의
   별도 관심사, 이미 신호화됨), 이 스크립트가 받는 범위 안에서는 codex 자신의 캡이
   없다.
2. **대안의 blast radius.** truncation 에 강제 FAIL 을 걸면 "review-blocking"의 의미가
   조용히 넓어진다: 리팩터, 벤더링된 의존성 업데이트, 생성 코드 커밋처럼 충분히 큰 PR은
   변경 자체에 위험이 전혀 없어도 *Kiro leg* 만으로 fail-closed 된다. 이는 결함 수정이
   아니라 게이트 스코프 자체의 정책 변경이며, 이 ADR이 남기는 명시적 결정 없이는
   일어나서는 안 된다.
3. **실제 커버리지 손실을 위한 직교·더 좁은 severity 축이 이미 있다.**
   `coverage-severe.flag`는 (a) 벤더 패밀리 전체 전멸(`CODEX_DEAD || KIRO_ALL_DEAD`),
   (b) lens 하나가 벤더 패밀리 하나의 응답을 통째로 잃음(`lens-coverage-gap.txt`)에서
   독립적으로 세워진다. 둘 다 "교차확인이 전혀 없었다"는 진짜 사례다. truncation 은
   그게 아니라 "한 벤더의 교차확인이 diff 를 더 적게 봤다"는, 엄밀히 더 약한 조건이다.

이는 명시적 사용자 결정(2026-07-08, 이 CI 설계를 공유하는 sibling repo들을 고치던 중
동일한 질문에 대해 받은 응답)으로 확인된 의도된 설계다 — "게이트를 더 엄격하게" 대신
"현재 설계(advisory) 유지"를 선택했다. 이 결정은 이 repo 하나가 아니라 이 fleet 전체에
적용된다.

## 결과

- diff 가 `KIRO_DIFF_CAP`을 넘는 PR은 종합 리뷰에 `✂️ **Kiro diff truncated**` 배너가
  보이지만, 그것만으로 게이트가 막히지 않는다.
- 종합 코멘트를 읽는 사람이 배너를 직접 인지해야 한다 — 이건 강제 메커니즘이 아니라
  신호다. 향후 사고로 이 신호가 일상적으로 무시된다는 게 드러나면, 이 ADR을 재검토할
  근거가 된다(그 자리에서 편집이 아니라 supersede).
- `KIRO_DIFF_CAP`을 올리는 것(이미 사용자 override 가능, 검증·커널한도 clamp 됨)을
  막지 않는다 — truncation 이 실전에서 자주 발생한다면 이는 이미 있는 별도의,
  non-blocking 완화책이다.

## 참고

- `scripts/pr-review/run-panel.sh`(`KIRO_DIFF_CAP`, `kiro-diff-truncated.flag`,
  `coverage-severe.flag`)
- `scripts/pr-review/synthesize.sh`(truncation 배너)
- PR #7 리뷰 라운드들(이 ADR이 대응을 공식화하는 MAJOR finding)
- Sibling repo들의 동일한 트레이드오프, 동일한 사용자 결정: oh-my-cloud-skills, ttobak,
  claude-code-usage-dashboard, multi-region-architecture, aws-fsi-demo, AWS-Demo-Platform
