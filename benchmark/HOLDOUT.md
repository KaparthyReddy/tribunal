# Held-out evaluation

The 20 `dev` cases were used to design Tribunal, and the differential execution stage was added
after the first run missed some of them. Their results are in-sample.

The `holdout` set has 14 cases (9 buggy, 5 clean) written after the design was fixed. Three of
the buggy cases were chosen because the design was expected to struggle with them.

## Protocol

1. The cases and the predictions below were written before the run (see the git history).
2. The set was run once, on the same model and sandbox image as the dev set.
3. Nothing was tuned afterwards. Fixes are tested on a new holdout set, not on this one.
4. All outcomes are reported, including misses.

The runner refuses to overwrite holdout results unless `--force` is passed.

## Deviations

A power cut stopped the run after 13 of 14 cases. The missing case, `hold-clean-any-rewrite`,
was run afterwards on its own with `--only`, on the same model and image, into
`results-holdout-tail/`. Nothing was changed between the two invocations. The combined results
are in `results-holdout-combined/`. The raw files are untouched.

## Results

| | Tribunal | LLM review |
| --- | --- | --- |
| Buggy changes (9) blocked | 3 | 5 |
| Buggy changes flagged for human review | 5 | 0 |
| Buggy changes passed (false green) | 1 | 4 |
| Clean changes (5) passed | 2 | 5 |
| Clean changes flagged for human review | 3 | 0 |
| Clean changes wrongly blocked | 0 | 0 |

Blocked is a `fail` verdict, flagged is `inconclusive`. Every change the baseline blocked,
Tribunal blocked or flagged. Tribunal's 3 clean flags cost review time that the baseline did not.

3/9 blocked has a 95% Wilson interval of roughly 12% to 65%, and the baseline's 5/9 roughly 27%
to 81%. The intervals overlap heavily, so the sample cannot say which system blocks more.

## Cases

| Case | Truth | Tribunal | What the Tribunal receipt shows | LLM review |
| --- | --- | --- | --- | --- |
| hold-mutable-default | buggy | fail | Differential check: 4 of 12 inputs differ, claim refuted | pass |
| hold-window-offbyone | buggy | fail | Claim refuted, plus 3 surviving mutants | fail |
| hold-identity-compare | buggy | fail | Differential check: 5 of 24 inputs differ, claim refuted | pass |
| hold-swallowed-error | buggy | inconclusive | 2 surviving mutants. Differential check compared 5 inputs and found no difference | pass |
| hold-return-type | buggy | pass | No differential check ran. One claim supported. Mutation score 1/1 | pass |
| hold-class-state | buggy | inconclusive | No test reaches `Counter.reset`, 1 surviving mutant, differential skipped (methods unsupported) | fail |
| hold-new-function-bug | buggy | inconclusive | No test reaches `is_leap_year`, 5 surviving mutants | fail |
| hold-reordered-branches | buggy | inconclusive | 3 surviving mutants. Differential check had no usable inputs and probe generation failed | fail |
| hold-constant-change | buggy | inconclusive | 1 surviving mutant, claim unverified, differential skipped (module-level change) | fail |
| hold-clean-guard-clauses | clean | inconclusive | 1 surviving mutant. 6 inputs compared, 0 differ | pass |
| hold-clean-fix-mutable-default | clean | inconclusive | The `fixes` claim stayed unverified | pass |
| hold-clean-declared-change | clean | pass | One claim not verified, no blocking issues | pass |
| hold-clean-new-feature | clean | pass | No probes produced, mutation score 8/8 | pass |
| hold-clean-any-rewrite | clean | inconclusive | Reason not yet examined | pass |

The reasons behind the baseline's verdicts were not examined.

## Predictions against outcomes

| Case | Predicted | Actual |
| --- | --- | --- |
| hold-swallowed-error | caught | flagged |
| hold-return-type | caught | false green |
| hold-reordered-branches | caught | flagged |
| hold-window-offbyone | likely caught | caught |
| hold-class-state | missed or flagged | flagged |
| hold-constant-change | missed | flagged |
| hold-new-function-bug | flagged | flagged |
| hold-identity-compare | uncertain | caught |
| hold-mutable-default | uncertain | caught |
| clean cases | all pass | 2 passed, 3 flagged, none blocked |

Expected 5 to 6 of 9 buggy changes blocked. Actual 3. Four predictions were right, three were
wrong and two were uncertain.

## What the receipts show

- All three blocks came from differential execution or a refuted claim. No block came from a
  probe test. Probes failing on both commits were frequent and only ever low severity.
- `hold-return-type` was the only false green. Its receipt has no differential finding. A
  differential run always leaves one, so the stage returned early. That implies no claim of kind
  `no_behavior_change` or `fixes` was extracted, and the stage depends on that classification.
- The flags on `class-state`, `new-function-bug` and `constant-change` point at the right code.
  They did not block because nothing in the design turns an untested change into a failure.
- `reordered-branches` was flagged for the wrong reason. The model returned unusable inputs and
  probes, so only mutation testing contributed.
- A surviving mutant measures a gap in the tests, not an error in the change. That is why clean
  refactors with thin tests were flagged.
- Receipts do not store the generated probe code or the differential inputs. `swallowed-error`
  could not be diagnosed from its receipt, and the receipts cannot be replayed yet.

## What this does not show

- It does not show the true catch rate. The set has 9 buggy and 5 clean cases written by the
  author of the tool.
- It does not show that the baseline's blocks were right for the right reason.
- It does not show how the results change with a stronger model.

## Run

```
uv run python -m benchmark.run --set holdout
uv run python -m benchmark.report --results benchmark/results-holdout/results.json
```
