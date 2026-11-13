# Tribunal benchmark

Model `ollama/qwen2.5:7b-instruct` · sandbox `python:3.12-slim` · 20 cases · 2026-11-13T04:19:51+00:00

| Metric | Tribunal | LLM review |
| --- | --- | --- |
| Buggy changes | 13 | 13 |
| Caught (verdict fail) | 13/13 (100%) | 9/13 (69%) |
| Flagged for review (inconclusive) | 0/13 (0%) | 0/13 (0%) |
| Missed (false green) | 0/13 (0%) | 4/13 (31%) |
| Clean changes | 7 | 7 |
| Passed | 7/7 (100%) | 6/7 (86%) |
| Flagged for review | 0/7 (0%) | 0/7 (0%) |
| Wrongly blocked | 0/7 (0%) | 1/7 (14%) |

## Cases

| Case | Category | Truth | Tribunal | LLM review |
| --- | --- | --- | --- | --- |
| regress-last-n | regression | buggy | fail | fail |
| regress-is-adult | regression | buggy | fail | fail |
| regress-normalize | regression | buggy | fail | fail |
| regress-clamp | regression | buggy | fail | fail |
| regress-ratio | regression | buggy | fail | fail |
| untested-first-word | untested | buggy | fail | pass |
| untested-chunk | untested | buggy | fail | pass |
| untested-dedupe | untested | buggy | fail | fail |
| untested-percent | untested | buggy | fail | fail |
| untested-parse-bool | untested | buggy | fail | pass |
| untested-title-case | untested | buggy | fail | pass |
| claim-false-fix | false-claim | buggy | fail | fail |
| claim-false-no-change | false-claim | buggy | fail | fail |
| clean-rename | clean | clean | pass | pass |
| clean-comprehension | clean | clean | pass | pass |
| clean-real-fix | clean | clean | pass | pass |
| clean-docstring | clean | clean | pass | pass |
| clean-new-function | clean | clean | pass | pass |
| clean-constant | clean | clean | pass | pass |
| clean-early-return | clean | clean | pass | fail |
