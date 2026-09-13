# Specialist review module

[README.md](README.md), [the project contract](../../docs/pr-review-specialists.md)
and [ADR-002](../../docs/decisions/ADR-002-specialist-review-protocol.md) define
this module. CI selects `ROLE_REVIEW=1`; legacy entrypoints remain for fixtures.
Preserve BASE/head provenance, the exact approved exclusions, full required-role
coverage, nonce/receipt binding, secret custody and existing invocation budgets.
Missing coverage never becomes PASS. Instructions, docs and active output are
English. Run the README's offline checks; model access needs native evidence.
