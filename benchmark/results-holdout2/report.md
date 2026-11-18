# Tribunal benchmark

Model `ollama/qwen2.5:7b-instruct` · sandbox `python:3.12-slim` · 17 cases · 2026-11-18T08:04:22+00:00

| Metric | Tribunal | LLM review |
| --- | --- | --- |
| Buggy changes | 11 | 11 |
| Caught (verdict fail) | 7/11 (64%) | 4/11 (36%) |
| Flagged for review (inconclusive) | 2/11 (18%) | 0/11 (0%) |
| Missed (false green) | 2/11 (18%) | 7/11 (64%) |
| Clean changes | 6 | 6 |
| Passed | 6/6 (100%) | 6/6 (100%) |
| Flagged for review | 0/6 (0%) | 0/6 (0%) |
| Wrongly blocked | 0/6 (0%) | 0/6 (0%) |

## Cases

| Case | Category | Truth | Tribunal | LLM review |
| --- | --- | --- | --- | --- |
| h2-dict-get | semantics | buggy | fail | pass |
| h2-default-arg | semantics | buggy | pass | fail |
| h2-sort-tiebreak | semantics | buggy | pass | pass |
| h2-int-division | semantics | buggy | fail | pass |
| h2-method-overdraft | state | buggy | inconclusive | fail |
| h2-truncate-boundary | boundary | buggy | fail | pass |
| h2-regex-anchor | semantics | buggy | fail | fail |
| h2-new-word-count | new-code | buggy | inconclusive | pass |
| h2-label-boundary | boundary | buggy | fail | pass |
| h2-mutates-argument | state | buggy | fail | pass |
| h2-tests-catch-it | regression | buggy | fail | fail |
| h2-clean-first-even | clean | clean | pass | pass |
| h2-clean-palindrome-fix | clean | clean | pass | pass |
| h2-clean-declared-change | clean | clean | pass | pass |
| h2-clean-optional-param | clean | clean | pass | pass |
| h2-clean-dead-code | clean | clean | pass | pass |
| h2-clean-comment-only | clean | clean | pass | pass |
