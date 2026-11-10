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
| `receipt_id`, `submission_id` | Identifiers. |
| `repo`, `base_sha`, `head_sha` | What was verified. A new commit needs a new receipt. |
| `verdict` | `pass`, `fail` or `inconclusive`. |
| `rationale` | Why the Judge decided this. |
| `claims`, `claim_results` | Extracted claims and whether each was supported, refuted or unverifiable. |
| `findings` | Issues from every agent, most severe first. |
| `commands` | Every sandboxed command: argv, image, exit code, output, duration. |
| `issued_at` | UTC timestamp. |

Findings and claim results reference commands by index, so every conclusion points at the
output that produced it.

## Canonical bytes

The signed bytes are the body serialized with sorted keys, no whitespace, and non-ASCII
characters left as is:

```python
json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
```

The signature covers these bytes, not the digest.

## Verify with Python

```python
import base64
import hashlib
import json
import sys

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

receipt = json.load(open(sys.argv[1]))
data = json.dumps(
    receipt["body"], sort_keys=True, separators=(",", ":"), ensure_ascii=False
).encode("utf-8")

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
