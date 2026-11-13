# Held-out evaluation

The 20 `dev` cases were used to design Tribunal, and the differential execution stage was added
after the first run missed some of them. Their results are in-sample.

The `holdout` set has 14 cases (9 buggy, 5 clean) that were written after the design was fixed.
Three of the buggy cases were chosen because the current design is expected to struggle with them.

## Protocol

1. These cases and the predictions below are committed before the first run.
2. The set is run once, on the same model and sandbox image as the dev set.
3. Nothing is tuned afterwards. Fixes go in as new dev cases and a new holdout set.
4. All outcomes are reported, including misses.

The runner refuses to overwrite holdout results unless `--force` is passed.

## Predictions

| Case | Prediction | Why |
| --- | --- | --- |
| hold-swallowed-error | caught | Differential run sees `ValueError` on base and `0` on head |
| hold-return-type | caught | `repr` differs between list and tuple |
| hold-reordered-branches | caught | Depends on the model choosing a multiple of 15 |
| hold-window-offbyone | likely caught | Depends on a non-empty list being chosen |
| hold-identity-compare | uncertain | Needs equal strings that are distinct objects |
| hold-mutable-default | uncertain | Needs two calls with different arguments to expose shared state |
| hold-class-state | missed or flagged | Differential execution only covers top-level functions |
| hold-constant-change | missed | The change is module-level and no function is targeted |
| hold-new-function-bug | flagged | The function is not in base, and probes fail on both commits |
| clean cases | all pass | Risks: hold-clean-declared-change, hold-clean-fix-mutable-default |

Expected overall: 5 to 6 of 9 buggy caught, 0 to 1 of 5 clean wrongly blocked.

## Reading the result

A catch rate of 9/9 gives a 95% lower bound of about 70% (Wilson interval). A rate of 6/9 is
consistent with true rates between roughly 35% and 88%. Nine cases can show gross failure or
success but cannot separate similar systems.

## Run

```
uv run python -m benchmark.run --set holdout
uv run python -m benchmark.report --results benchmark/results-holdout/results.json
```
