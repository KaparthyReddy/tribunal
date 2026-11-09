import base64
import os
import stat
from pathlib import Path

import pytest

from tribunal.models import ReceiptBody, SignedReceipt, Verdict
from tribunal.receipts import ReceiptSigner, canonical_bytes, digest_of, verify_receipt


def _body() -> ReceiptBody:
    return ReceiptBody(
        submission_id="sub_x",
        repo="o/r",
        base_sha="a" * 40,
        head_sha="b" * 40,
        verdict=Verdict.PASS,
        rationale="ok",
    )


def test_sign_and_verify(tmp_path: Path) -> None:
    signer = ReceiptSigner.load_or_create(tmp_path / "key.pem")
    receipt = signer.sign(_body())
    assert verify_receipt(receipt)
    assert receipt.digest == digest_of(receipt.body)


def test_canonical_bytes_are_stable() -> None:
    body = _body()
    assert canonical_bytes(body) == canonical_bytes(body.model_copy(deep=True))


def test_tampered_body_fails(tmp_path: Path) -> None:
    signer = ReceiptSigner.load_or_create(tmp_path / "key.pem")
    receipt = signer.sign(_body())
    receipt.body.verdict = Verdict.FAIL
    assert not verify_receipt(receipt)


def test_tampered_signature_fails(tmp_path: Path) -> None:
    signer = ReceiptSigner.load_or_create(tmp_path / "key.pem")
    receipt = signer.sign(_body())
    receipt.signature = base64.b64encode(bytes(64)).decode("ascii")
    assert not verify_receipt(receipt)


def test_trusted_key_mismatch_fails(tmp_path: Path) -> None:
    signer = ReceiptSigner.load_or_create(tmp_path / "a.pem")
    other = ReceiptSigner.load_or_create(tmp_path / "b.pem")
    receipt = signer.sign(_body())
    assert verify_receipt(receipt, trusted_public_key=signer.public_key_b64)
    assert not verify_receipt(receipt, trusted_public_key=other.public_key_b64)


def test_key_is_persisted(tmp_path: Path) -> None:
    path = tmp_path / "key.pem"
    first = ReceiptSigner.load_or_create(path)
    second = ReceiptSigner.load_or_create(path)
    assert first.public_key_b64 == second.public_key_b64


def test_json_roundtrip_still_verifies(tmp_path: Path) -> None:
    signer = ReceiptSigner.load_or_create(tmp_path / "key.pem")
    receipt = signer.sign(_body())
    restored = SignedReceipt.model_validate_json(receipt.model_dump_json())
    assert verify_receipt(restored)


@pytest.mark.skipif(os.name == "nt", reason="posix permissions")
def test_key_file_permissions(tmp_path: Path) -> None:
    path = tmp_path / "key.pem"
    ReceiptSigner.load_or_create(path)
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
