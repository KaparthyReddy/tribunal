# Second held-out evaluation: results

Registered in [HOLDOUT2.md](HOLDOUT2.md) and [HOLDOUT2-AMENDMENTS.md](HOLDOUT2-AMENDMENTS.md).
The cases, predictions and success criteria were committed before the redesign existed.

## Runs

| Version | Code | Output |
| --- | --- | --- |
| v3 | `main` after batch 9c | `results-holdout2/` |
| v2 | tag `v2-pre-batch9`, run from a git worktree with `benchmark/` taken from `main` | `results-holdout2-v2/` |

Each version was run once, on the same model (`ollama/qwen2.5:7b-instruct`) and sandbox image.
The LLM review baseline was run once, with v3. No run was interrupted. The git commit of each run
is recorded in the `meta` of its `results.json`.

## Results

| | v3 | v2 | LLM review |
| --- | --- | --- | --- |
| Buggy changes (11) blocked | 7 | 7 | 4 |
| Buggy changes flagged for human review | 2 | 3 | 0 |
| Buggy changes passed (false green) | 2 | 1 | 7 |
| Clean changes (6) passed | 6 | 5 | 6 |
| Clean changes flagged for human review | 0 | 1 | 0 |
| Clean changes wrongly blocked | 0 | 0 | 0 |

7/11 blocked has a 95% Wilson interval of roughly 35% to 85%, and 4/11 roughly 15% to 65%. The
intervals overlap.

## Pre-registered criteria

v3 was to be judged a failure if any of these held.

| Criterion | Result | Triggered |
| --- | --- | --- |
| Blocks any clean change | 0 blocked | no |
| Passes fewer than 4 of the 6 clean changes | 6 passed | no |
| Has more false greens than v2 | 2 against 1 | **yes** |
| Blocks fewer buggy changes than v2 | 7 against 7 | no |

v3 was to be judged to have worked only if it blocked at least 2 more buggy changes than v2 and
its clean results were no worse. It blocked 0 more.

**Verdict: v3 failed its pre-registered test.**

## Cases

| Case | Truth | v3 | v2 | LLM review | v3 predicted | v2 predicted |
| --- | --- | --- | --- | --- | --- | --- |
| h2-dict-get | buggy | fail | fail | pass | uncertain, leaning false green | uncertain |
| h2-default-arg | buggy | pass | inconclusive | fail | caught | caught |
| h2-sort-tiebreak | buggy | pass | inconclusive | pass | uncertain | uncertain |
| h2-int-division | buggy | fail | fail | pass | caught | caught |
| h2-method-overdraft | buggy | inconclusive | pass | fail | flagged | flagged or false green |
| h2-truncate-boundary | buggy | fail | fail | pass | uncertain | uncertain |
| h2-regex-anchor | buggy | fail | fail | fail | uncertain | uncertain |
| h2-new-word-count | buggy | inconclusive | inconclusive | pass | flagged | flagged |
| h2-label-boundary | buggy | fail | fail | pass | false green | false green or flagged |
| h2-mutates-argument | buggy | fail | fail | pass | caught | false green |
| h2-tests-catch-it | buggy | fail | fail | fail | caught | caught |
| h2-clean-first-even | clean | pass | pass | pass | pass | flagged |
| h2-clean-palindrome-fix | clean | pass | inconclusive | pass | pass | flagged |
| h2-clean-declared-change | clean | pass | pass | pass | pass | pass |
| h2-clean-optional-param | clean | pass | pass | pass | pass | pass or flagged |
| h2-clean-dead-code | clean | pass | pass | pass | pass | flagged or pass |
| h2-clean-comment-only | clean | pass | pass | pass | pass | pass or flagged |

## Predictions against outcomes

| | v3 | v2 |
| --- | --- | --- |
| Definite predictions | 13 | 13 |
| Right | 11 | 9 |
| Wrong | 2 (default-arg, label-boundary) | 4 (default-arg, label-boundary, mutates-argument, first-even) |
| Expected buggy changes blocked | 5 to 7, actual 7 | 3 to 5, actual 7 |
| Expected false greens | 2 to 4, actual 2 | 2 or more, actual 1 |
| Expected clean changes passed | 4 to 6, actual 6 | 3 to 4, actual 5 |

v3 landed inside its predicted ranges. v2 landed outside all three, in its own favor.

## Differences between the versions

The two versions agreed on 13 of 17 cases. Both blocked the same 7 buggy changes. The redesign
changed four outcomes:

| Case | v2 | v3 | Effect |
| --- | --- | --- | --- |
| h2-method-overdraft | pass | inconclusive | better |
| h2-clean-palindrome-fix | inconclusive | pass | better |
| h2-default-arg | inconclusive | pass | worse |
| h2-sort-tiebreak | inconclusive | pass | worse |

The two regressions are both buggy changes that went from flagged to passed. These are the false
greens that the success criteria were written to catch.

## The set favors the tool

10 of the 11 buggy cases carry a "no behavior change" claim, and 9 of those edit a plain
top-level function, which is the shape differential execution is built for. The first held-out
set had more cases outside that shape (methods, a module constant, a new function), and v2
blocked 3 of 9 there. The difference between 3 of 9 and 7 of 11 may reflect the cases more than
the tool.

## What this does not show

- It does not show the true catch rate. The set has 11 buggy and 6 clean cases written by the
  author of the tool, who also designed the redesign.
- It does not show that the baseline's blocks were right for the right reason.
- Both versions ran once, so run-to-run variance is unknown.
- It does not show how results change with a stronger model.

## Not yet examined

- Why v3 passed `h2-default-arg` and `h2-sort-tiebreak`, which v2 flagged.
- How v2 blocked `h2-label-boundary` and `h2-mutates-argument`, which it was predicted to miss.
- Whether the 7 shared blocks came from the same findings in both versions.

These are answered by the receipts under `results-holdout2/receipts/` and
`results-holdout2-v2/receipts/`.
