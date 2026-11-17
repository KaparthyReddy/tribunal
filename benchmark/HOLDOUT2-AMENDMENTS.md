# Amendments to the holdout2 registration

This file was written after the redesign was implemented and before any holdout2 run. The cases,
predictions and success criteria in [HOLDOUT2.md](HOLDOUT2.md) are unchanged. This file lists where
the code differs from the design that file describes, so results can be read against it.

## Differences from the registered design

1. A fail-to-pass test supports a `fixes` claim only when exactly one fix is claimed, the failure
   is not an import error, and the base suite passed on its own beforehand.
2. Calls that only work on the new signature, such as a new parameter, are excluded from
   comparison. The registration did not mention this. It is needed for backward-compatible
   additions.
3. Coverage is required on both commits: added lines on head and removed lines on base.
4. Two deterministic rules were added: identical syntax trees (comments, formatting, docstrings),
   and structural changes (new functions, removed functions nothing references). They back the
   `h2-clean-comment-only` and `h2-clean-dead-code` predictions.
5. An undeclared behavior difference is `medium`, or `info` when the diff also edits tests or
   claims a fix.
6. A claim whose text is a bare kind token, such as `no_behavior_change`, is replaced by the
   matching sentence from the PR text, or dropped.
7. Surviving mutants are demoted to test gaps only when behavior is shown identical, and never for
   new functions.
8. The model gets one repair retry when its output is not valid JSON or does not match the
   expected shape. This also applies to the LLM-review baseline, so baseline results from v3 and
   from the pre-redesign tag are not strictly comparable. The baseline is run once, with v3.
9. The Skeptic runs before the Characterizer. This has no effect on verdicts.

## Dependencies the predictions rest on

- `h2-clean-palindrome-fix` is predicted to pass only if the model extracts exactly one claim of
  kind `fixes`. Any other labeling leaves the claim unverified.
- Predictions for `h2-default-arg`, `h2-int-division` and `h2-mutates-argument` assume the model
  picks an input that exposes the difference. The coverage rule can make the model try again, but
  a difference that does not change which lines run is not forced.
- `h2-dict-get` and `h2-label-boundary` are built to defeat line coverage, and a pass is expected.
