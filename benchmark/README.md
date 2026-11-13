# Benchmark

Scores Tribunal against a plain LLM review on seeded changes. Each case is a tiny git
repository with a base commit and a head commit, built on the fly.

## Sets

| Set | Cases | Purpose |
| --- | --- | --- |
| dev | 20 | Used while designing Tribunal. Results are in-sample. |
| holdout | 14 | Written after the design was fixed. Run once. See [HOLDOUT.md](HOLDOUT.md). |

Dev categories: regression (5), untested (6), false-claim (2), clean (7).
Holdout categories: state, semantics, errors, types, new-code, hidden-in-refactor, constant, clean.

## Systems

| System | Input | Output |
| --- | --- | --- |
| Tribunal | The repository, base and head commits, title, description, test command | A signed verdict from sandboxed evidence |
| LLM review | Title, description and diff in one prompt | approve or reject |

Both use the same model from your `.env`.

## Metrics

| Metric | Definition |
| --- | --- |
| Caught | Buggy change with a `fail` verdict |
| Flagged | Buggy or clean change with an `inconclusive` verdict, sent to a human |
| False green | Buggy change with a `pass` verdict |
| Wrongly blocked | Clean change with a `fail` verdict |

Flagged changes are reported separately and are not counted as catches.

## Run

```
uv run python -m benchmark.run --list
uv run python -m benchmark.run --only regress-last-n,clean-rename
uv run python -m benchmark.run
uv run python -m benchmark.run --set holdout
uv run python -m benchmark.report
```

Results go to `benchmark/results/` for dev and `benchmark/results-<set>/` for the others.
`results.json` is rewritten after every case, so a partial run is usable. Signed receipts are
saved under `receipts/`. `report.html` is a self-contained page.

Useful flags: `--set`, `--skip-baseline`, `--skip-tribunal`, `--out DIR`, `--force`.

## Caveats

- The bugs are synthetic and small, and the sample sizes are small. Treat rates as indicative.
- Results depend heavily on the model. Small local models write weaker probes.
- The baseline never runs code. That is the point of the comparison, not a flaw in it.
- A counted catch is a `fail` verdict. The benchmark does not check that the cited reason is the
  seeded bug, so spot-check the receipts.
- Tribunal makes many more model calls and runs far more slowly than a single review prompt.
