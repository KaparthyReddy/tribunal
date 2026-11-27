# Dogfooding: Tribunal on its own repository

Two runs on this repository with real dependencies, using `--build-env`.

## Setup

| | |
| --- | --- |
| Image | Built from the base commit's `pyproject.toml`: 13 dependencies, `dev` group included |
| Base image | `python:3.12`, because Tribunal's own tests call `git`, which the slim image lacks |
| Limits | `TRIBUNAL_SANDBOX_TIMEOUT_S=300`, `TRIBUNAL_SANDBOX_MEMORY=1g` |
| Test command | `python -m pytest -m "not docker" -q` |
| Model | `ollama/qwen2.5:7b-instruct` |

## Run 1: a formatting-only commit

The most recent commit touching `src/` was formatter output. Every changed file had an identical
syntax tree, so the static check reported no runtime change.

- Verdict: inconclusive. All 4 commands replayed.
- Two functions in `cli.py` were still flagged as untested. Their tests call them through a CLI
  test runner, which a call graph that links calls by name cannot follow.
- Result: a change with identical syntax trees now reports untested code at `info` level instead of
  `medium`. Sampled agreement from differential inputs does not do this, because it cannot prove
  identity. Separately, `.txt` files no longer count as documentation, since they can be runtime
  data.

## Run 2: a seeded regression

On a throwaway branch, `ELEVATED_BELOW` in `src/tribunal/ledger.py` changed from `0.75` to `0.5`,
described as "Tidy ledger thresholds. No behavior change."

Verdict: FAIL, exit code 1, 10 commands. Replay reproduced all 10, including the full test run.

| Stage | Result |
| --- | --- |
| Test command | `high`: passes on base, fails on head. Deterministic |
| "No behavior change" claim | `high`: refuted by the same base and head result, by a fixed rule |
| Differential check | `low`: skipped, the model's input generation failed even after the retry |
| Probes | `low` x4: every probe failed on both commits, so none carried signal |
| Blast radius | `info`: module-level changes are not coverage-checked |

## What this shows

- The dependency build, the offline run of a real test suite, the signed receipt and the replay
  work on a real repository.
- It does not show detection quality. The verdict came from the project's own tests failing, and a
  plain `pytest` run reports the same failure. What Tribunal added was the environment, the link
  from that failure to the false "no behavior change" claim, and a signed record that can be
  replayed.
- The model-driven stages contributed nothing to this verdict.

## Reproduce

```
git switch -c dogfood-demo
sed -i '' 's/^ELEVATED_BELOW = 0.75$/ELEVATED_BELOW = 0.5/' src/tribunal/ledger.py
git commit -qam "Tidy ledger thresholds"
export TRIBUNAL_SANDBOX_IMAGE=python:3.12 TRIBUNAL_SANDBOX_TIMEOUT_S=300 TRIBUNAL_SANDBOX_MEMORY=1g
tribunal submit --repo-path . --base HEAD~1 --head HEAD --title "Tidy ledger thresholds" --description "Tidy ledger thresholds. No behavior change." --test-cmd 'python -m pytest -m "not docker" -q' --build-env --json > receipt.json
tribunal replay receipt.json --repo-path .
```

On Linux use `sed -i` without the empty string.
