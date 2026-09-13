# PR review module

The active pipeline is `.github/workflows/pr-review.yml`: `run-panel.sh` runs
its legacy matrix, `synthesize.sh` chairs it, and `lib.sh` supplies shared helpers.
Their current limits, safety controls and Korean/English output remain authoritative.

[README.md](README.md) records the planned specialist interfaces and offline tests;
[ADR-002](../../docs/decisions/ADR-002-specialist-review-protocol.md) owns the decision.
New documentation uses English. Protocol output switches to English only at the
separate activation. Run the documented tests after the library lands. Preserve
source custody, configured providers, budgets and the active coverage policy.

The offline protocol and its tests are now installed; provider activation remains separate.

Executor helpers and their offline tests are installed. The operational workflow
stays legacy until activation; README defines command, isolation and limit contracts.
