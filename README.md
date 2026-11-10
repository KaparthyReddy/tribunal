# Tribunal

Adversarial verification for AI-written code.

Coding agents produce diffs. Tribunal decides whether anyone should trust them.
Four agents attack a change at its exact commit and issue a signed, replayable verdict.

| Agent | Job |
|-------|-----|
| Skeptic | Writes probe tests and mutants designed to break the change |
| Auditor | Replays every claim in the PR description in a sandbox at the exact SHA |
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

## Quick start

```bash
git clone https://github.com/KaparthyReddy/tribunal.git
cd tribunal
cp .env.example .env
uv sync
docker info
```

Put `ANTHROPIC_API_KEY` in `.env`, then verify a change:

```bash
uv run tribunal submit --repo-path /path/to/repo --base HEAD~1 --head HEAD \
  --title "Fix parser" --description "Fixes the crash on empty input." \
  --test-cmd "python -m pytest -q" --agent codex
```

Exit codes: `0` pass, `1` fail, `2` inconclusive, `3` error.

## Docs

- [Architecture](docs/architecture.md)
- [Receipt format](docs/receipt-format.md)
- [GitHub Action](docs/github-action.md)
- [MCP clients](docs/mcp-clients.md)

## Status

Under active development.
