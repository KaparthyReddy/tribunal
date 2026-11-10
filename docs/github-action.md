# GitHub Action

The action verifies every pull request and reports the verdict three ways: a job summary,
a pull request comment, and the job result.

## Usage

```yaml
name: Tribunal

on:
  pull_request:

permissions:
  contents: read
  pull-requests: write

jobs:
  verify:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0
      - uses: KaparthyReddy/tribunal/action@main
        with:
          anthropic-api-key: ${{ secrets.ANTHROPIC_API_KEY }}
          sandbox-image: ghcr.io/your-org/your-test-image:latest
          test-command: python -m pytest -q
```

`fetch-depth: 0` is required. Tribunal diffs against the merge base of the pull request.

## Inputs

| Input | Default | Meaning |
| --- | --- | --- |
| `anthropic-api-key` | required | Key for the verification agents. |
| `github-token` | `github.token` | Used to post the comment. |
| `test-command` | empty | Test command, run inside the sandbox image. |
| `sandbox-image` | `python:3.12-slim` | Image for every sandboxed command. |
| `model` | `claude-sonnet-5-5` | Model used by the agents. |
| `agent` | PR author | Agent name used by the trust ledger. |
| `comment` | `true` | Post or update one verdict comment. |
| `fail-on` | `fail` | `fail` or `inconclusive`. |

## Outputs

`verdict`, `receipt-id` and `digest`. The full signed receipt is uploaded as the
`tribunal-receipt` artifact.

## Exit behavior

| Verdict | Job result |
| --- | --- |
| pass | success |
| fail | failure |
| inconclusive | success, or failure with `fail-on: inconclusive` |

## Sandbox image

The sandbox has no network, so the image must contain the project's test dependencies.
Build one in your own pipeline and pass it as `sandbox-image`. The default image only has the
Python standard library, so probes written with `unittest` run but `pytest` based suites do not.

## Security

- Use the `pull_request` trigger. Do not use `pull_request_target`.
- Pull requests from forks do not receive repository secrets, so the action cannot run on them.
- Pull request code only runs inside the sandbox container, never on the runner.

## Cost

Each run makes several model calls: claim extraction, a plan and an evaluation per claim, and
probe generation. Gate the workflow with a label or a path filter on busy repositories.
