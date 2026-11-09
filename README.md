# Tribunal

Adversarial verification for AI-written code.

Coding agents produce diffs. Tribunal decides whether anyone should trust them.
Four agents attack a change at its exact commit and issue a signed, replayable verdict.

| Agent | Job |
|-------|-----|
| Skeptic | Writes tests, fuzz cases and mutants designed to break the change |
| Auditor | Replays every claim in the PR description in a sandbox at the exact SHA |
| Blast-radius | Uses a call graph to find affected code and checks it is covered |
| Judge | Combines the evidence into a signed verdict with a receipt |

A human reads the verdict and the receipt, not the raw diff.

## Interfaces

- MCP server: `submit`, `verdict`, `replay`
- GitHub Action: posts the verdict as a check run
- CLI: `tribunal submit`, `tribunal verify-receipt`

## Guarantees

- Every command runs in a Docker sandbox with no network, dropped capabilities and resource limits
- Every receipt is canonical JSON, SHA-256 digested and Ed25519 signed
- A verdict is bound to a head SHA; a new commit invalidates old evidence

## Quick start

```bash
git clone https://github.com/KaparthyReddy/tribunal.git
cd tribunal
cp .env.example .env
uv sync
docker info
```

## Status

Under active development.
