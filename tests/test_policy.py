import pytest

from tribunal.config import Settings
from tribunal.sandbox import PolicyError, SandboxPolicy


def test_valid_policy() -> None:
    SandboxPolicy(image="python:3.12-slim").validate()


def test_digest_required() -> None:
    with pytest.raises(PolicyError):
        SandboxPolicy(image="python:3.12-slim", require_digest=True).validate()
    SandboxPolicy(image="python@sha256:" + "a" * 64, require_digest=True).validate()


@pytest.mark.parametrize(
    "kwargs",
    [
        {"image": ""},
        {"image": "x", "timeout_s": 0},
        {"image": "x", "cpus": 0},
        {"image": "x", "pids_limit": 0},
        {"image": "x", "max_output_bytes": 10},
    ],
)
def test_invalid_policy(kwargs: dict) -> None:
    with pytest.raises(PolicyError):
        SandboxPolicy(**kwargs).validate()


def test_from_settings() -> None:
    settings = Settings(_env_file=None, sandbox_image="img:1", sandbox_timeout_s=7)
    policy = SandboxPolicy.from_settings(settings)
    assert policy.image == "img:1"
    assert policy.timeout_s == 7
