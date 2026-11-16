# Receipt format

A receipt is a JSON object with four fields.

| Field | Meaning |
| --- | --- |
| `body` | Everything that was decided and the evidence behind it. |
| `digest` | SHA-256 of the canonical body, hex encoded. |
| `signature` | Ed25519 signature over the canonical body bytes, base64 encoded. |
| `public_key` | Raw 32 byte Ed25519 public key, base64 encoded. |

## Body

| Field | Meaning |
| --- | --- |
| `version` | `2` for current receipts. Receipts made before replay support are `1`. |
| `receipt_id`, `submission_id` | Identifiers. |
| `repo`, `base_sha`, `head_sha` | What was verified. A new commit needs a new receipt. |
| `verdict` | `pass`, `fail` or `inconclusive`. |
| `rationale` | Why the Judge decided this. |
| `claims`, `claim_results` | Extracted claims and whether each was supported, refuted or unverifiable. |
| `findings` | Issues from every agent, most severe first. |
| `commands` | Every sandboxed command, see below. |
| `blobs` | Generated files the commands used, keyed by the SHA-256 of their content. |
| `issued_at` | UTC timestamp. |

Findings and claim results reference commands by index, so every conclusion points at the
output that produced it.

## Commands

| Field | Meaning |
| --- | --- |
| `argv`, `image` | What ran and in which image. |
| `exit_code`, `timed_out`, `stdout`, `stderr`, `duration_s` | What happened. Output is clipped. |
| `side` | `base` or `head`: the commit the command ran against. |
| `overlay` | Files placed on that checkout first, as relative path to blob digest. |
| `timeout_s` | The timeout that applied. |

Overlays hold what Tribunal generated: probe tests, differential inputs and the driver script,
and mutated source files. The files themselves are in `blobs`, so the signed body contains
everything needed to run a command again. Total blob size is capped at 512 KB. A command whose
file did not fit is recorded without it and cannot be replayed.

## Canonical bytes

The signed bytes are the body serialized with sorted keys, no whitespace, and non-ASCII
characters left as is:

```python
json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
```

The signature covers these bytes, not the digest.

For `version` 1 receipts, `blobs` and the `side`, `overlay` and `timeout_s` fields of each
command are left out of the signed bytes, because those receipts were signed before the fields
existed. A version 1 receipt that carries any of them is invalid, since they would be unsigned.

## Verify with Python

```python
import base64
import hashlib
import json
import sys

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

receipt = json.load(open(sys.argv[1]))
body = receipt["body"]
if body.get("version", 1) < 2:
    body.pop("blobs", None)
    for command in body["commands"]:
        for name in ("side", "overlay", "timeout_s"):
            command.pop(name, None)

data = json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
assert hashlib.sha256(data).hexdigest() == receipt["digest"], "digest mismatch"
key = Ed25519PublicKey.from_public_bytes(base64.b64decode(receipt["public_key"]))
key.verify(base64.b64decode(receipt["signature"]), data)
print("valid")
```

Floating point values such as `duration_s` use Python's shortest round-trip representation.
Verifiers in other languages must reproduce that formatting.

## Trusting the signer

A valid signature only proves the receipt was not altered and was signed by the holder of
`public_key`. Compare `public_key` with the key your Tribunal server publishes:

```
tribunal public-key
tribunal verify-receipt receipt.json --public-key BASE64_KEY
```

## Replay

```
tribunal replay receipt.json --repo-path /path/to/repo
```

Replay verifies the receipt, checks out the exact base and head commits from the repository,
and for each command applies its overlay, runs it in the recorded image with the recorded
timeout, then restores the checkout. It compares the exit code and timeout flag, and the output
after masking durations and memory addresses.

| Status | Meaning |
| --- | --- |
| `reproduced` | Same outcome and same output. |
| `output_differs` | Same outcome, different output. |
| `diverged` | A different exit code or timeout. |
| `skipped` | No replay data, a missing artifact, or an unsafe path. |

Overall the result is `reproduced`, `diverged`, `incomplete` (something was skipped) or `empty`.
The exit code is 0, 1, 2 and 2.

Limits:

- Replay assumes each command starts from a clean checkout plus its overlay. A command that
  depends on files an earlier command wrote will not replay faithfully.
- Environment variables are not recorded.
- The recorded image must still be available. Pin images by digest to make that dependable.
- Receipts from before version 2 carry no replay data and come back `incomplete`.
- Replay shows the evidence is real and reproducible. It does not show the generated tests
  were good ones.
