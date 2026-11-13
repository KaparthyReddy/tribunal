# Tribunal benchmark

Model `ollama/qwen2.5:7b-instruct` · sandbox `python:3.12-slim` · 14 cases · 2026-11-13T05:08:43+00:00

| Metric | Tribunal | LLM review |
| --- | --- | --- |
| Buggy changes | 9 | 9 |
| Caught (verdict fail) | 3/9 (33%) | 5/9 (56%) |
| Flagged for review (inconclusive) | 5/9 (56%) | 0/9 (0%) |
| Missed (false green) | 1/9 (11%) | 4/9 (44%) |
| Clean changes | 5 | 5 |
| Passed | 2/5 (40%) | 5/5 (100%) |
| Flagged for review | 3/5 (60%) | 0/5 (0%) |
| Wrongly blocked | 0/5 (0%) | 0/5 (0%) |

## Cases

| Case | Category | Truth | Tribunal | LLM review |
| --- | --- | --- | --- | --- |
| hold-mutable-default | state | buggy | fail | pass |
| hold-window-offbyone | semantics | buggy | fail | fail |
| hold-identity-compare | semantics | buggy | fail | pass |
| hold-swallowed-error | errors | buggy | inconclusive | pass |
| hold-return-type | types | buggy | pass | pass |
| hold-class-state | state | buggy | inconclusive | fail |
| hold-new-function-bug | new-code | buggy | inconclusive | fail |
| hold-reordered-branches | hidden-in-refactor | buggy | inconclusive | fail |
| hold-constant-change | constant | buggy | inconclusive | fail |
| hold-clean-guard-clauses | clean | clean | inconclusive | pass |
| hold-clean-fix-mutable-default | clean | clean | inconclusive | pass |
| hold-clean-declared-change | clean | clean | pass | pass |
| hold-clean-new-feature | clean | clean | pass | pass |
| hold-clean-any-rewrite | clean | clean | inconclusive | pass |
