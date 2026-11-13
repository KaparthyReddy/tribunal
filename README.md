# Tribunal

Adversarial verification for AI-written code.

Coding agents produce diffs. Tribunal decides whether anyone should trust them.
Agents attack a change at its exact commit, in a sandbox, and issue a signed, replayable verdict.

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

## Benchmark

20 seeded changes, each a tiny git repository with a base and a head commit: 13 buggy, 7 clean.
Both systems use the same local model (`ollama/qwen2.5:7b-instruct`). The baseline is a single
prompt that sees the title, description and diff and answers approve or reject.

| | Tribunal v1 | Tribunal v2 | LLM review |
| --- | --- | --- | --- |
| Buggy changes caught | 9/13 (69%) | 13/13 (100%) | 9/13 (69%) |
| Buggy changes passed (false green) | 3/13 (23%) | 0/13 (0%) | 4/13 (31%) |
| Clean changes passed | 7/7 | 7/7 | 6/7 |
| Clean changes wrongly blocked | 0/7 | 0/7 | 1/7 |

By category, Tribunal v2 caught 5/5 regressions the tests catch, 6/6 bugs the tests miss, and
2/2 false claims. The baseline caught 5/5, 2/6 and 2/2.

What the numbers mean:

- v2 adds differential execution, which runs the changed functions on both commits with
  model-chosen inputs and compares the outputs. It was designed after v1 missed the cases above,
  so the v2 column is an in-sample result. It shows the mechanism works on these bugs. It is not
  an estimate of the catch rate on unseen changes.
- 20 cases and one run is a small sample, and the bugs are small synthetic functions.
- A counted catch is a `fail` verdict. The benchmark does not check that the cited reason is the
  seeded bug, so spot-check receipts in `benchmark/results/receipts/`.
- Tribunal runs several model calls and sandboxed commands per change and takes about a minute on a
  7B local model. The baseline takes seconds.

Reproduce it with the commands in [benchmark/README.md](benchmark/README.md). Raw results for both
Tribunal versions are in `benchmark/results-v1/` and `benchmark/results/`.

## Models

Tribunal runs on a local model through Ollama by default. No API key is needed.
Anthropic is supported by setting `TRIBUNAL_LLM_PROVIDER=anthropic` and `ANTHROPIC_API_KEY`.
Weaker models produce weaker probes and more `inconclusive` verdicts, never a false `pass`.

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

## Status

Under active development. Python only. The sandbox has no network, so test dependencies must
already be in the sandbox image.
