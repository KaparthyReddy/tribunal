import hashlib
from datetime import UTC, datetime
from pathlib import Path

from tribunal.agents.base import Evidence
from tribunal.models import CommandRecord


def _record(**kwargs) -> CommandRecord:
    return CommandRecord(
        argv=["x"],
        image="img",
        exit_code=0,
        duration_s=0.1,
        started_at=datetime.now(UTC),
        **kwargs,
    )


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class _Runner:
    def run(self, workdir, argv, *, env=None, timeout_s=None) -> CommandRecord:
        return _record()


def test_side_comes_from_the_registered_directories(tmp_path: Path) -> None:
    base, head, other = tmp_path / "base", tmp_path / "head", tmp_path / "other"
    evidence = Evidence(sides={base: "base", head: "head"})
    evidence.add(_record(), workdir=base)
    evidence.add(_record(), workdir=head)
    evidence.add(_record(), workdir=other)
    evidence.add(_record())
    assert [command.side for command in evidence.commands] == ["base", "head", None, None]


def test_overlay_is_stored_as_digests_with_deduplicated_blobs(tmp_path: Path) -> None:
    evidence = Evidence(sides={tmp_path: "head"})
    overlay = {"pkg/a.py": "print(1)\n", "pkg/__init__.py": ""}
    evidence.add(_record(), workdir=tmp_path, overlay=overlay)
    evidence.add(_record(), workdir=tmp_path, overlay=overlay)

    assert evidence.commands[0].overlay == {
        "pkg/__init__.py": _sha(""),
        "pkg/a.py": _sha("print(1)\n"),
    }
    assert evidence.blobs == {_sha(""): "", _sha("print(1)\n"): "print(1)\n"}


def test_blob_budget_skips_storing_but_keeps_the_digest(tmp_path: Path) -> None:
    evidence = Evidence(blob_budget=10)
    evidence.add(_record(), overlay={"small.py": "x=1\n", "big.py": "y" * 100})

    overlay = evidence.commands[0].overlay
    assert overlay["big.py"] == _sha("y" * 100)
    assert _sha("x=1\n") in evidence.blobs
    assert _sha("y" * 100) not in evidence.blobs


def test_timeout_is_filled_in_only_when_the_runner_did_not_set_it() -> None:
    evidence = Evidence()
    evidence.add(_record(), timeout_s=30)
    evidence.add(_record(timeout_s=60), timeout_s=30)
    assert [command.timeout_s for command in evidence.commands] == [30, 60]


def test_run_returns_the_stored_record(tmp_path: Path) -> None:
    evidence = Evidence(sides={tmp_path: "base"})
    index, record = evidence.run(_Runner(), tmp_path, ["x"], timeout_s=5, overlay={"a.py": "1\n"})
    assert index == 0
    assert record is evidence.commands[0]
    assert record.side == "base"
    assert record.timeout_s == 5
    assert record.overlay == {"a.py": _sha("1\n")}
