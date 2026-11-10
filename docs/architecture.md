# Architecture

Tribunal answers one question: should anyone trust this diff?

A coding agent produces a change. Tribunal checks the change at its exact commit, in a sandbox,
and returns a signed verdict. A human reads the verdict and the receipt, not the raw diff.

## Pipeline

Every submission runs the same stages in order.

| Stage | Component | What it does |
| --- | --- | --- |
| 1 | Workspaces | Exports the base and head commits with `git archive` into two throwaway directories. |
| 2 | Claims | Extracts verifiable claims from the PR title and description. |
| 3 | Blast radius | Builds a tree-sitter call graph of the head commit, finds changed functions, and checks that a test reaches each one. |
| 4 | Auditor | Runs the test command on base and head, then plans and runs checks for each claim and judges the evidence. |
| 5 | Skeptic | Writes adversarial probe tests and runs them on both commits, then runs mutation testing on the changed lines. |
| 6 | Judge | Applies a deterministic policy to all findings and signs a receipt. |

Only the Judge decides the verdict, and it uses no LLM. Agents produce findings and evidence.

## Verdict policy

| Verdict | Condition |
| --- | --- |
| fail | Any finding at `high` or above, or any refuted claim. |
| inconclusive | Any `medium` finding, any unverified `fixes` or `no_behavior_change` claim, or no executable evidence. |
| pass | Everything else. |

Probes that fail on base and head are `low`. A probe that passes on base and fails on head is
`high`. A test command that passes on base and fails on head is `high`.

## Trust ledger

Each receipt updates a per-agent, per-repository history. The score is
`(passes + 1) / (total + 2)`. With at least five verdicts:

| Score | Scrutiny | Judge policy |
| --- | --- | --- |
| 0.75 and above | standard | fail at `high`, review at `medium` |
| 0.50 to 0.75 | elevated | fail at `high`, review at `low` |
| below 0.50 | high | fail at `medium`, review at `low` |

## Sandbox

Every command runs in a Docker container with no network, a read-only root filesystem, all
capabilities dropped, `no-new-privileges`, and memory, CPU and PID limits. The workspace is a
disposable copy mounted at `/work`. Output is clipped and every command is recorded in the
receipt.

## Known limits

- The sandbox has no network. The sandbox image must already contain the project's test
  dependencies. A networked setup phase is planned.
- Call graph and mutation testing support Python only. Other languages produce an `info` finding.
- Claim extraction and check planning use an LLM. A claim that cannot be checked with executable
  evidence stays unverified instead of being assumed true.
- Receipts prove what was run and what it printed. They do not prove the absence of bugs.
