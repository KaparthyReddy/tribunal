# Benchmark

Scores Tribunal against a plain LLM review on 20 seeded changes. Each case is a tiny git
repository with a base commit and a head commit, built on the fly.

| Category | Cases | Meaning |
| --- | --- | --- |
| regression | 5 | The change breaks something the existing tests catch |
| untested | 6 | The change breaks behavior the existing tests do not cover |
| false-claim | 2 | The PR description claims something the code does not do |
| clean | 7 | A correct change, used to measure false alarms |

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
uv run python -m benchmark.report
```

`results.json` is rewritten after every case, so a partial run is usable. Signed receipts are
saved under `results/receipts/`. `report.html` is a self-contained page.

Useful flags: `--skip-baseline`, `--skip-tribunal`, `--out DIR`.

## Caveats

- The bugs are synthetic and small, and 20 cases is a small sample. Treat rates as indicative.
- Results depend heavily on the model. Small local models write weaker probes.
- The baseline never runs code. That is the point of the comparison, not a flaw in it.
- Tribunal makes many more model calls and runs far more slowly than a single review prompt.
