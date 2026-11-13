# Tribunal

Adversarial verification for AI-written code.

Coding agents produce diffs. Tribunal decides whether anyone should trust them.
Agents attack a change at its exact commit, in a sandbox, and issue a signed verdict with an
evidence receipt.

| Agent | Job |
|-------|-----|
| Skeptic | Writes probe tests and mutants designed to break the change |
| Auditor | Replays every claim in the PR description in a sandbox at the exact SHA |
| Characterizer | Runs the changed functions on both commits and compares the outputs |
| Blast-radius | Uses a call graph to find affected code and checks that tests reach it |
| Judge | Applies a deterministic policy to the evidence and signs a receipt |

A human reads the verdict and the receipt, not the raw diff.

## Interfaces

- CLI: `tribunal submit`, `verdict`, `verify-receipt`, `trust`, `public-key`
- HTTP API: `tribunal serve`, interactive docs at `/docs`
- MCP server: `tribunal mcp` with `submit`, `verdict`, `verify`
- GitHub Action: verifies pull requests and comments the verdict

## Guarantees

- Every command runs in a Docker sandbox with no network, dropped capabilities and resource limits
- Every receipt is canonical JSON, SHA-256 digested and Ed25519 signed
- A verdict is bound to a head SHA; a new commit invalidates old evidence
- Only the Judge decides the verdict, and it uses no LLM

Receipts record every command and its output. They do not yet include the generated probe code
and differential inputs, so they cannot be replayed. This is the next fix.

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

### Held-out set (14 cases, run once)

| | Tribunal | LLM review |
| --- | --- | --- |
| Buggy changes (9) blocked | 3 | 5 |
| Buggy changes flagged for human review | 5 | 0 |
| Buggy changes passed (false green) | 1 | 4 |
| Clean changes (5) passed | 2 | 5 |
| Clean changes flagged for human review | 3 | 0 |
| Clean changes wrongly blocked | 0 | 0 |

How to read it:

- **The dev result did not generalize.** On unseen cases Tribunal blocked 3 of 9 and the baseline
  5 of 9. The intervals overlap heavily, so the sample cannot say which blocks more.
- **Tribunal passed fewer bugs.** It passed 1 of 9 buggy changes against 4 for the baseline, and
  every change the baseline blocked, Tribunal blocked or flagged.
- **That cost review time.** Tribunal flagged 3 of 5 clean changes and the baseline flagged none.
  A gate that sends many clean changes to a human is not yet usable.
- **The blocks came from running code.** All three came from differential execution, and the
  baseline missed two of them. The baseline blocked four bugs that Tribunal only flagged.
- **The one false green** happened because no differential check ran. The stage depends on the
  model classifying a claim as "no behavior change".
- Small samples, one run, a 7B model, and cases written by the tool's author. Predictions
  and the full case table, misses included, are in [benchmark/HOLDOUT.md](benchmark/HOLDOUT.md).

Raw results are in `benchmark/results-v1/`, `benchmark/results/`, `benchmark/results-holdout/`
and `benchmark/results-holdout-combined/`. Reproduce with [benchmark/README.md](benchmark/README.md).

## Models

Tribunal runs on a local model through Ollama by default. No API key is needed.
Anthropic is supported by setting `TRIBUNAL_LLM_PROVIDER=anthropic` and `ANTHROPIC_API_KEY`.
Weaker models produce weaker probes and more `inconclusive` verdicts. On the held-out set one
buggy change still got a `pass`.

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
  --test-cmd "python -m unittest" --agent codex
```

Exit codes: `0` pass, `1` fail, `2` inconclusive, `3` error.

## Docs

- [Architecture](docs/architecture.md)
- [Receipt format](docs/receipt-format.md)
- [GitHub Action](docs/github-action.md)
- [MCP clients](docs/mcp-clients.md)
- [Benchmark](benchmark/README.md)
- [Held-out evaluation](benchmark/HOLDOUT.md)

## Status

Under active development. Python only. The sandbox has no network, so test dependencies must
already be in the sandbox image. Differential execution covers top-level functions only.
