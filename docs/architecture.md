# Architecture

Tribunal answers one question: should anyone trust this diff?

A coding agent produces a change. Tribunal checks the change at its exact commit, in a sandbox,
and returns a signed verdict. A human reads the verdict and the receipt, not the raw diff.

## Pipeline

Every submission runs the same stages in order.

| Stage | Component | What it does |
| --- | --- | --- |
| 1 | Workspaces | Exports the base and head commits with `git archive` into two throwaway directories. |
| 2 | Claims | Extracts verifiable claims from the PR title and description. Phrases such as "no behavior change" and "callers are unaffected" always produce a `no_behavior_change` claim. |
| 3 | Blast radius | Builds a tree-sitter call graph of the head commit, finds changed functions, and checks that a test reaches each one. |
| 4 | Auditor | Runs the test command on base and head, then plans and runs checks for each claim and judges the evidence. |
| 5 | Skeptic | Writes adversarial probe tests and runs them on both commits, then runs mutation testing on the changed lines. |
| 6 | Characterizer | Runs every changed top-level function on both commits with model-chosen inputs, traces which changed lines ran, and compares results and argument state. |
| 7 | Fail-to-pass | Checks whether a test changed in the diff fails on the base commit and passes on head. |
| 8 | Judge | Applies a deterministic policy to all findings and signs a receipt. |

Only the Judge decides the verdict, and it uses no LLM. Agents produce findings and evidence.

## Claim support

A model can refute a claim with evidence. It cannot support a `no_behavior_change` or `fixes`
claim. Those are supported only by fixed rules, and any model judgment of "supported" is
downgraded to unverified.

A `no_behavior_change` claim is supported when one of these holds:

- the base and head syntax trees are identical, so only comments, formatting or docstrings changed
- only new functions, or removed functions that nothing references, changed
- the differential inputs gave identical results and identical argument state on both commits,
  every changed executable line ran on its side (added lines on head, removed lines on base), and
  nothing changed outside the characterizer's reach

It is refuted by any difference in a result or in argument state.

A `fixes` claim is supported when either holds:

- a test changed in the diff fails on the base commit and passes on head. The base suite must pass
  on its own first, the failure must not be an import error, and exactly one fix must be claimed.
- an input the claim describes raised on base and returns normally on head

It is refuted when the described input still fails on both commits.

## Differential execution

The model chooses call inputs. The sandbox runs them on base, on head, and on head a second time.
Inputs whose head results differ between the two head runs are dropped as nondeterministic. A
driver traces line execution inside the sandbox. If changed lines did not run, the model gets one
more round of inputs aimed at them. Lines still unrun become a `medium` finding.

- A call that only works on the new signature, such as a newly added parameter, is not compared.
- A difference with no `no_behavior_change` claim is `medium`, or `info` when the diff also edits
  tests or claims a fix.
- When behavior is shown identical, surviving mutants are reported as test gaps at `info` level.
  New code is exempt, so untested new functions stay `medium`.

The model chooses inputs but never interprets the results.

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
receipt, along with the files it used, so it can be replayed.

## Known limits

- The sandbox has no network. The sandbox image must already contain the project's test
  dependencies. `tribunal build-image` builds one from the base commit's dependency files
  with network access, and only that build step has it. See [Dependencies](dependencies.md).
- Differential execution calls top-level functions only. Methods, class bodies and code that
  cannot be imported are reported as outside its reach, which blocks support for the claim.
- Coverage is line based. A change that alters behavior on an input without changing which lines
  run, such as a moved comparison boundary, can pass with every line executed.
- Claim extraction, check planning and input generation use an LLM. A claim that cannot be
  checked with executable evidence stays unverified instead of being assumed true.
- A fail-to-pass test can fail on base for reasons other than the fix, such as a new feature.
  Import errors are excluded, other causes are not.
- Python only. Receipts prove what was run and what it printed. They do not prove the absence of
  bugs.
