import base64
import hashlib
import json
import os
from pathlib import Path

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)

from tribunal.models import ReceiptBody, SignedReceipt

BODY_FIELDS_V2 = ("blobs",)
COMMAND_FIELDS_V2 = ("side", "overlay", "timeout_s")


def has_v2_data(body: ReceiptBody) -> bool:
    if body.blobs:
        return True
    return any(
        command.side is not None or command.overlay or command.timeout_s is not None
        for command in body.commands
    )


def canonical_bytes(body: ReceiptBody) -> bytes:
    payload = body.model_dump(mode="json")
    if body.version < 2:
        for name in BODY_FIELDS_V2:
            payload.pop(name, None)
        for command in payload.get("commands", []):
            for name in COMMAND_FIELDS_V2:
                command.pop(name, None)
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def digest_of(body: ReceiptBody) -> str:
    return hashlib.sha256(canonical_bytes(body)).hexdigest()


class ReceiptSigner:
    def __init__(self, private_key: Ed25519PrivateKey) -> None:
        self._private_key = private_key

    @classmethod
    def load_or_create(cls, path: Path) -> "ReceiptSigner":
        if path.exists():
            key = serialization.load_pem_private_key(path.read_bytes(), password=None)
            if not isinstance(key, Ed25519PrivateKey):
                raise ValueError(f"{path} does not contain an Ed25519 private key")
            return cls(key)

        key = Ed25519PrivateKey.generate()
        pem = key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )
        path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "wb") as handle:
            handle.write(pem)
        return cls(key)

    @property
    def public_key_b64(self) -> str:
        raw = self._private_key.public_key().public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )
        return base64.b64encode(raw).decode("ascii")

    def sign(self, body: ReceiptBody) -> SignedReceipt:
        if body.version < 2 and has_v2_data(body):
            raise ValueError("a version 1 receipt cannot carry replay data")
        data = canonical_bytes(body)
        signature = self._private_key.sign(data)
        return SignedReceipt(
            body=body,
            digest=hashlib.sha256(data).hexdigest(),
            signature=base64.b64encode(signature).decode("ascii"),
            public_key=self.public_key_b64,
        )


def verify_receipt(receipt: SignedReceipt, trusted_public_key: str | None = None) -> bool:
    if trusted_public_key is not None and receipt.public_key != trusted_public_key:
        return False
    if receipt.body.version < 2 and has_v2_data(receipt.body):
        return False
    data = canonical_bytes(receipt.body)
    if hashlib.sha256(data).hexdigest() != receipt.digest:
        return False
    try:
        public_key = Ed25519PublicKey.from_public_bytes(base64.b64decode(receipt.public_key))
        public_key.verify(base64.b64decode(receipt.signature), data)
    except (InvalidSignature, ValueError):
        return False
    return True
