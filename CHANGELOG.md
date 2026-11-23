# Changelog

## 0.1.0 - 2026-11-23

First release.

### Added

- Verification pipeline: claim extraction, blast radius from a call graph, claim audit,
  adversarial probes and mutation testing, differential execution with line tracing and
  argument-state comparison, fail-to-pass checks, and a deterministic Judge with no LLM
- A rule that a model can refute a "no behavior change" or "fixes" claim but cannot support one
- Ed25519 signed receipts with the generated probes, inputs and mutated sources inside the signed
  body, and `tribunal replay` to re-run every command at the exact commit
- Per-agent trust ledger that raises scrutiny for agents with weak history
- `tribunal build-image` and `--build-env`: dependencies installed from the base commit's
  requirements with network access, every analysis then offline in that image
- CLI, HTTP API, MCP server (`submit`, `verdict`, `verify`, `replay`) and a GitHub Action
- Local models through Ollama by default, Anthropic optional
- Benchmarks against a plain LLM review: a 20 case dev set and two held-out sets with predictions
  registered before the runs

### Known limitations

- Python only. Differential execution calls top-level functions only
- Sampled inputs can show that two versions differ but cannot show that they never do
- The benchmark sets are small, synthetic and written by the author of the tool. On the second
  held-out set the redesigned detection logic failed its own pre-registered criteria, and the
  results moved a lot between sets. See `benchmark/HOLDOUT.md` and `benchmark/HOLDOUT2-RESULTS.md`
- The GitHub Action is unit-tested against mocked GitHub APIs and has not run on a real pull
  request
- Receipts made before version 2 carry no replay data
