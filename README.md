# Tribunal

Adversarial verification for AI-written code.

Coding agents produce diffs. Tribunal decides whether anyone should trust them.
Agents attack a change at its exact commit, in a sandbox, and issue a signed verdict with a
receipt that can be replayed.

| Agent | Job |
|-------|-----|
| Skeptic | Writes probe tests and mutants designed to break the change |
| Auditor | Replays every claim in the PR description in a sandbox at the exact SHA |
| Characterizer | Runs the changed functions on both commits and compares results and argument state |
| Blast-radius | Uses a call graph to find affected code and checks that tests reach it |
| Judge | Applies a deterministic policy to the evidence and signs a receipt |

A human reads the verdict and the receipt, not the raw diff.

## Interfaces

- CLI: `tribunal submit`, `verdict`, `verify-receipt`, `replay`, `trust`, `public-key`
- HTTP API: `tribunal serve`, interactive docs at `/docs`
- MCP server: `tribunal mcp` with `submit`, `verdict`, `verify`, `replay`
- GitHub Action: verifies pull requests and comments the verdict

## Guarantees

- Every command runs in a Docker sandbox with no network, dropped capabilities and resource limits
- Every receipt is canonical JSON, SHA-256 digested and Ed25519 signed
- A verdict is bound to a head SHA; a new commit invalidates old evidence
- Only the Judge decides the verdict, and it uses no LLM
- A model can refute a "no behavior change" or "fixes" claim, but it cannot support one. Support
  comes only from fixed rules, described in [Architecture](docs/architecture.md)
- Receipts carry the generated probe code, differential inputs and mutated sources, so
  `tribunal replay` can re-run every command at the exact commit and compare the outcomes

Replay shows that the evidence is real and reproducible. It does not show that the generated
tests were good ones. Receipts made before version 2, including the earlier benchmark receipts,
carry no replay data. See [Receipt format](docs/receipt-format.md) for the limits.

## Benchmark

Tribunal is compared with a plain LLM review on seeded changes. Each case is a tiny git
repository with a base and a head commit. Both systems use the same local model
(`ollama/qwen2.5:7b-instruct`). The baseline is a single prompt that sees the title, description
and diff and answers approve or reject.

### Dev set (20 cases, in-sample)

| | Tribunal v1 | Tribunal v2 | LLM review |
| --- | --- | --- | --- |
| Buggy changes caught | 9/13 (69%) | 13/13 (100%) | 9/13 (69%) |
| Buggy changes passed (false green) | 3/13 | 0/13 | 4/13 |
| Clean changes passed | 7/7 | 7/7 | 6/7 |
| Clean changes wrongly blocked | 0/7 | 0/7 | 1/7 |

v2 added differential execution after v1 missed some of these exact cases, so this column
measures how well the design fits these bugs, not how well it works in general.

### First held-out set (14 cases, run once)

| | Tribunal v2 | LLM review |
| --- | --- | --- |
| Buggy changes (9) blocked | 3 | 5 |
| Buggy changes flagged for human review | 5 | 0 |
| Buggy changes passed (false green) | 1 | 4 |
| Clean changes (5) passed | 2 | 5 |
| Clean changes flagged for human review | 3 | 0 |
| Clean changes wrongly blocked | 0 | 0 |

The dev result did not generalize. Tribunal passed fewer bugs than the baseline but flagged 3 of
5 clean changes, and every block came from the differential check. Predictions, the full case
table and a label caveat are in [benchmark/HOLDOUT.md](benchmark/HOLDOUT.md).

### Second held-out set (17 cases, run once per version)

This set tests a redesign of the detection logic (v3) against the code before it (v2). The cases,
predictions and success criteria were committed before the redesign existed.

| | Tribunal v3 | Tribunal v2 | LLM review |
| --- | --- | --- | --- |
| Buggy changes (11) blocked | 7 | 7 | 4 |
| Buggy changes flagged for human review | 2 | 3 | 0 |
| Buggy changes passed (false green) | 2 | 1 | 7 |
| Clean changes (6) passed | 6 | 5 | 6 |
| Clean changes flagged for human review | 0 | 1 | 0 |
| Clean changes wrongly blocked | 0 | 0 | 0 |

How to read it:

- **The redesign failed its pre-registered test.** v3 had more false greens than v2 (2 against 1),
  which the criteria count as failure. It also blocked no more buggy changes than v2 (7 against 7),
  short of the 2 more that the criteria required to call it a success.
- **The two versions blocked the same 7 changes.** The redesign changed four outcomes. Two
  improved (one false green became a flag, one flagged clean change became a pass). Two got worse,
  and both are buggy changes that went from flagged to passed.
- **Both versions beat the baseline on this set,** 7 of 11 caught against 4, and neither blocked
  a clean change. The intervals overlap, and the set favors the tool: 9 of the 11 buggy cases
  are an edited top-level function with a "no behavior change" claim, which is what differential
  execution targets.
- **Results move a lot between sets.** v2 blocked 3 of 9 on the first held-out set and 7 of 11
  here. Neither number should be read as the tool's catch rate.

Cases, predictions, scoring and what is still unexamined are in
[benchmark/HOLDOUT2-RESULTS.md](benchmark/HOLDOUT2-RESULTS.md).

Raw results are in `benchmark/results-v1/`, `benchmark/results/`, `benchmark/results-holdout/`,
`benchmark/results-holdout-tail/`, `benchmark/results-holdout-combined/`,
`benchmark/results-holdout2/` and `benchmark/results-holdout2-v2/`. Reproduce with
[benchmark/README.md](benchmark/README.md).

## Models

Tribunal runs on a local model through Ollama by default. No API key is needed.
Anthropic is supported by setting `TRIBUNAL_LLM_PROVIDER=anthropic` and `ANTHROPIC_API_KEY`.
Weaker models produce weaker probes and more `inconclusive` verdicts. Every benchmark set so
far has had at least one buggy change that got a `pass`.

## Quick start

```bash
git clone https://github.com/KaparthyReddy/tribunal.git
cd tribunal
cp .env.example .env
uv sync
ollama pull qwen2.5:7b-instruct
docker info
```

Set `TRIBUNAL_OLLAMA_MODEL=qwen2.5:7b-instruct` in `.env`, then verify a change:

```bash
uv run tribunal submit --repo-path /path/to/repo --base HEAD~1 --head HEAD \
  --title "Fix parser" --description "Fixes the crash on empty input." \
  --test-cmd "python -m unittest" --agent codex --json > receipt.json
uv run tribunal replay receipt.json --repo-path /path/to/repo
```

Exit codes for `submit`: `0` pass, `1` fail, `2` inconclusive, `3` error.
Exit codes for `replay`: `0` reproduced, `1` diverged, `2` incomplete, `3` error.

Tests that need third-party packages need an image that contains them. Add `--build-env` to build
one from the base commit's requirements, and use `python -m pytest` so the project is importable:

    uv run tribunal submit --repo-path /path/to/repo --base main --head HEAD --build-env \
      --test-cmd "python -m pytest -q"
      
## Docs

- [Architecture](docs/architecture.md)
- [Receipt format](docs/receipt-format.md)
- [GitHub Action](docs/github-action.md)
- [MCP clients](docs/mcp-clients.md)
- [Benchmark](benchmark/README.md)
- [First held-out evaluation](benchmark/HOLDOUT.md)
- [Second held-out evaluation](benchmark/HOLDOUT2.md) and its [results](benchmark/HOLDOUT2-RESULTS.md)

## Status

Under active development. Python only. The sandbox has no network, so test dependencies must
already be in the sandbox image. Differential execution covers top-level functions only, and
sampled inputs can show that two versions differ but cannot show that they never do.
