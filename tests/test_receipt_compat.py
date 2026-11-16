from datetime import UTC, datetime
from pathlib import Path

import pytest

from tribunal.models import CommandRecord, ReceiptBody, SignedReceipt, Verdict
from tribunal.receipts import ReceiptSigner, canonical_bytes, verify_receipt

FIXTURE = Path(__file__).parent / "fixtures" / "receipt_v1.json"


def _body(**kwargs) -> ReceiptBody:
    return ReceiptBody(
        submission_id="sub_x",
        repo="o/r",
        base_sha="a" * 40,
        head_sha="b" * 40,
        verdict=Verdict.PASS,
        rationale="ok",
        **kwargs,
    )


def _command(**kwargs) -> CommandRecord:
    return CommandRecord(
        argv=["x"],
        image="img",
        exit_code=0,
        duration_s=0.1,
        started_at=datetime.now(UTC),
        **kwargs,
    )


def test_receipt_signed_before_version_2_still_verifies() -> None:
    receipt = SignedReceipt.model_validate_json(FIXTURE.read_text(encoding="utf-8"))
    assert receipt.body.version == 1
    assert verify_receipt(receipt)


def test_version_1_canonical_bytes_leave_out_version_2_fields() -> None:
    text = canonical_bytes(_body(version=1, commands=[_command()])).decode("utf-8")
    for name in ('"blobs"', '"side"', '"overlay"', '"timeout_s"'):
        assert name not in text


def test_version_2_canonical_bytes_include_version_2_fields() -> None:
    text = canonical_bytes(_body(commands=[_command()])).decode("utf-8")
    for name in ('"blobs"', '"side"', '"overlay"', '"timeout_s"'):
        assert name in text


def test_new_receipts_are_version_2(tmp_path: Path) -> None:
    signer = ReceiptSigner.load_or_create(tmp_path / "key.pem")
    receipt = signer.sign(_body())
    assert receipt.body.version == 2
    assert verify_receipt(receipt)


def test_blob_tampering_invalidates_a_version_2_receipt(tmp_path: Path) -> None:
    signer = ReceiptSigner.load_or_create(tmp_path / "key.pem")
    receipt = signer.sign(_body(blobs={"a" * 64: "print(1)\n"}))
    assert verify_receipt(receipt)
    receipt.body.blobs = {"a" * 64: "print(2)\n"}
    assert not verify_receipt(receipt)


def test_overlay_tampering_invalidates_a_version_2_receipt(tmp_path: Path) -> None:
    signer = ReceiptSigner.load_or_create(tmp_path / "key.pem")
    command = _command(side="head", overlay={"a.py": "a" * 64}, timeout_s=30)
    receipt = signer.sign(_body(commands=[command]))
    assert verify_receipt(receipt)
    receipt.body.commands[0].overlay = {"a.py": "b" * 64}
    assert not verify_receipt(receipt)


def test_version_1_receipt_cannot_gain_unsigned_replay_data(tmp_path: Path) -> None:
    signer = ReceiptSigner.load_or_create(tmp_path / "key.pem")
    receipt = signer.sign(_body(version=1, commands=[_command()]))
    assert verify_receipt(receipt)

    receipt.body.blobs = {"a" * 64: "import os\n"}
    assert not verify_receipt(receipt)

    receipt.body.blobs = {}
    receipt.body.commands[0].overlay = {"a.py": "a" * 64}
    assert not verify_receipt(receipt)


def test_signing_version_1_with_replay_data_is_refused(tmp_path: Path) -> None:
    signer = ReceiptSigner.load_or_create(tmp_path / "key.pem")
    with pytest.raises(ValueError):
        signer.sign(_body(version=1, blobs={"a" * 64: "x"}))
