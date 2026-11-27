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

## What the receipts show

Provenance. v3 ran at commit `42a9bf9` with a clean tree. v2 ran at `1f26476` and records a dirty
tree, because its worktree took `benchmark/` from `main`. Both record version 0.1.0, which was not
bumped between them, so the commit identifies the code.

The printout covered 7 of the 17 cases. The remaining ones were not examined.

### The two regressions

Both are buggy changes that v2 flagged and v3 passed.

| Case | v2 | v3 |
| --- | --- | --- |
| h2-default-arg | Claim supported by the model. 8 inputs compared, 0 differ. Medium finding: surviving mutant at `paging.py:1 (20 -> 21)`. Inconclusive | Claim supported by the fixed rule. 9 inputs compared, 0 differ. The same mutant reported as `info` (test gap, behavior unchanged). Pass |
| h2-sort-tiebreak | Claim unverifiable. 9 inputs compared, 0 differ. Inconclusive | Claim supported by the fixed rule. 6 inputs compared, 0 differ. No other findings. Pass |

- v3 supports a "no behavior change" claim when the sampled inputs agree and every changed line ran.
  For `sort-tiebreak` the changed line is a `return` that runs on every call, so the second
  condition cannot fail. The change only matters for ties in non-alphabetical order.
- For `default-arg` the changed line is the `def` line. Its default value is evaluated when the
  module is imported, so the "changed line ran" condition appears unable to fail for a signature
  change. This follows from how the driver traces and was not tested directly.
- Surviving mutants are demoted to test gaps when sampled inputs agree. In `default-arg` the
  surviving mutant sat on the changed value itself, so the demotion removed the one finding that
  pointed at it. Blast-radius findings are demoted only for syntactically identical code, so the
  two demotion rules rest on different evidence.
- The inputs were not printed. The likely cause is lists shorter than 10 items, since a page size
  of 10 against 20 only differs for longer lists. This is an inference and can be checked in the
  receipts' stored inputs.

### The two improvements

| Case | v2 | v3 |
| --- | --- | --- |
| h2-method-overdraft | The claim text was the bare token `no_behavior_change`, and the model marked it supported. Pass | The text was replaced with "No behavior change", model support was refused, and the method was reported as outside the differential check's reach. Inconclusive |
| h2-clean-palindrome-fix | `fixes` claim unverifiable. 10 inputs compared, 3 differ. Inconclusive | `fixes` claim supported. 7 inputs compared, 1 differ. Pass |

For `palindrome-fix` the base returns `False` instead of raising, so the targeted-input rule cannot
apply. The support most likely came from the fail-to-pass test the diff adds, which is an inference.

### Cases the author expected to defeat the design

- `h2-label-boundary` was predicted to pass in both versions. Both blocked it, with one of 5 (v3)
  or 7 (v2) inputs differing. The diff shows `>` becoming `>=`, so the model aimed an input at the
  boundary. The case tests whether the model reads the diff, not the limit of line coverage.
- `h2-dict-get` was blocked by both, with 3 of 8 inputs differing in v3 and 8 of 8 in v2. The diff
  shows `[]` becoming `.get`. The difference between 3 and 8 is unexplained.
- `h2-mutates-argument` was predicted to pass in v2, which cannot compare argument state. v2
  blocked it, with 2 of 12 inputs differing in return value or exception, probably strings or
  tuples, which `sorted()` accepts and `list.sort()` rejects. The case therefore does not isolate
  state comparison, and this evidence does not credit it to v3.

### The shared blocks

Of the 7 changes both versions blocked, 3 were examined (`dict-get`, `label-boundary`,
`mutates-argument`). All three were blocked by a refuted "no behavior change" claim from the
differential check in both versions. `int-division`, `truncate-boundary`, `regex-anchor` and
`tests-catch-it` were not examined.

### Conclusion

On this set v3 blocked no more than v2 and passed one more bug. The pre-registered verdict stands.
The receipts point at two defects in v3: the "changed lines ran" condition cannot fail for some
changes, and surviving mutants are demoted on sampled agreement. Neither was fixed or tested, since
this set is spent, and a fix would need a new held-out set.
