# Second held-out evaluation

The first held-out set (`holdout`) showed that the dev results did not generalize. Its failures
led to a redesign. This set (`holdout2`) tests that redesign on cases the redesign was not
tuned on. It has 17 cases: 11 buggy and 6 clean.

## Protocol

1. These cases and the predictions below are committed before any of the redesign exists.
2. The set is run once per version, with the same model and sandbox image as the earlier sets.
3. v2 is the code before the redesign, tagged `v2-pre-batch9`. v3 is the code after it.
4. v3 is run first. v2 is run afterwards from the tag, so v2's results cannot shape v3.
5. Nothing is tuned after a run. All outcomes are reported, including misses.
6. The success criteria below are fixed now.

The runner refuses to overwrite results without `--force`, and records the git commit of the
code it ran.

## What v3 is expected to change

1. Differential execution runs on every changed top-level function, whatever the claims say.
   A module-level change covers every top-level function in that file.
2. A "no behavior change" claim is supported only by a fixed rule: every changed executable
   line ran under the model's inputs and no output differed. The model asks for more inputs
   once if lines were not reached. A model's judgment alone can no longer support it.
3. A "fixes" claim is supported by a fixed rule: a test added in the diff fails on the base
   commit and passes on head, or a targeted input raised on base and returns on head.
4. Argument state after each call is compared along with the return value.
5. Phrases such as "no behavior change" and "callers are unaffected" always create a
   "no behavior change" claim.
6. A surviving mutant in covered code with identical behavior is reported as a test gap, not
   as a medium finding.
7. Unusable model output gets one repair retry.

## Known limits of v3, built into the set

- `h2-dict-get` and `h2-label-boundary` differ only on inputs that line coverage does not
  require. A change can have every line executed and still differ on a value nobody tried.
- `h2-method-overdraft` changes a method. Differential execution only calls top-level functions.
- `h2-new-word-count` is new code with no oracle for the intended behavior.

## Predictions

| Case | v2 | v3 | Why |
| --- | --- | --- | --- |
| h2-dict-get | uncertain | uncertain, leaning false green | Needs a missing key. Line coverage is satisfied by any key |
| h2-default-arg | caught | caught | Inputs that omit the size argument differ |
| h2-sort-tiebreak | uncertain | uncertain | Needs ties in non-alphabetical order |
| h2-int-division | caught | caught | A non-divisible list differs |
| h2-method-overdraft | flagged or false green | flagged | Methods are not called, so the claim stays unverified |
| h2-truncate-boundary | uncertain | uncertain | Needs a string exactly n long |
| h2-regex-anchor | uncertain | uncertain | Needs a string with a valid prefix |
| h2-new-word-count | flagged | flagged | No test reaches the new function |
| h2-label-boundary | false green or flagged | false green | Every line runs under typical inputs, the boundary needs weight 10 |
| h2-mutates-argument | false green | caught | v3 compares argument state after the call |
| h2-tests-catch-it | caught | caught | The existing tests fail on head |
| h2-clean-first-even | flagged | pass | Covered and identical, so surviving mutants become test gaps |
| h2-clean-palindrome-fix | flagged | pass | The added test fails on base and passes on head |
| h2-clean-declared-change | pass | pass | Differences exist but the diff edits the tests |
| h2-clean-optional-param | pass or flagged | pass | Existing calls give identical outputs |
| h2-clean-dead-code | flagged or pass | pass | A deletion has no changed executable lines |
| h2-clean-comment-only | pass or flagged | pass | Only a comment changed |

Expected v2: 3 to 5 of 11 buggy blocked, 2 or more false greens, 3 to 4 of 6 clean passed.
Expected v3: 5 to 7 of 11 buggy blocked, 2 to 4 false greens, 4 to 6 of 6 clean passed,
no clean change blocked.

## Success criteria

v3 is judged to have failed if any of these hold:

- it blocks any clean change
- it passes fewer than 4 of the 6 clean changes
- it has more false greens than v2
- it blocks fewer buggy changes than v2

v3 is judged to have worked only if it blocks at least 2 more buggy changes than v2 and its
clean results are no worse than v2's. With 11 and 6 cases, a smaller difference cannot be
separated from noise.

## Limits of the evidence

- The cases were written by the author of the tool, who also designed the redesign. The two
  cases built to defeat the design reduce that bias but do not remove it.
- 11 buggy and 6 clean cases are too few to measure rates. Read results as pass or fail on the
  criteria above.
- The model is a 7B local model, and one run per version does not show run-to-run variance.

## Run

```
uv run python -m benchmark.run --set holdout2
uv run python -m benchmark.report --results benchmark/results-holdout2/results.json
```
