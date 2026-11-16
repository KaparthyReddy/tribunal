import hashlib
from datetime import UTC, datetime
from pathlib import Path

import pytest
from typer.testing import CliRunner

from tribunal import cli
from tribunal.config import get_settings
from tribunal.models import CommandRecord, ReceiptBody, Verdict
from tribunal.receipts import ReceiptSigner
from tribunal.replay import (
    ReplayError,
    _overlaid,
    _safe_target,
    replay_receipt,
    runner_factory_from,
)
from tribunal.sandbox import SandboxPolicy, SandboxRunner, docker_available, workspace

cli_runner = CliRunner()
needs_docker = pytest.mark.skipif(not docker_available(), reason="docker unavailable")


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _command(
    side,
    argv=None,
    *,
    exit_code=0,
    stdout="",
    stderr="",
    overlay=None,
    timed_out=False,
    timeout_s=30,
) -> CommandRecord:
    return CommandRecord(
        argv=argv or ["true"],
        image="img",
        exit_code=exit_code,
        timed_out=timed_out,
        stdout=stdout,
        stderr=stderr,
        duration_s=0.1,
        started_at=datetime.now(UTC),
        side=side,
        overlay=overlay or {},
        timeout_s=timeout_s,
    )


def _signed(tmp_path: Path, shas, commands, blobs=None, version=2):
    signer = ReceiptSigner.load_or_create(tmp_path / "key.pem")
    return signer.sign(
        ReceiptBody(
            version=version,
            submission_id="sub_x",
            repo="o/r",
            base_sha=shas[0],
            head_sha=shas[1],
            verdict=Verdict.PASS,
            rationale="ok",
            commands=commands,
            blobs=blobs or {},
        )
    )


def test_replay_reproduces_and_applies_overlays(scenario, make_runner, is_head, tmp_path) -> None:
    repo, shas = scenario
    probe = "print('probe')\n"
    commands = [
        _command(
            "head",
            ["python", "-m", "unittest", "tribunal_probes.probe_1"],
            stdout="ok",
            overlay={"tribunal_probes/probe_1.py": _sha(probe)},
        ),
        _command("base", ["pytest"], stdout="base ok"),
    ]
    receipt = _signed(tmp_path, shas, commands, {_sha(probe): probe})

    seen = []

    def handler(workdir: Path, argv: list[str]) -> tuple[int, str, str]:
        probe_file = workdir / "tribunal_probes" / "probe_1.py"
        seen.append((is_head(workdir), argv[0], probe_file.exists()))
        if probe_file.exists():
            assert probe_file.read_text() == probe
        return 0, "ok" if argv[0] == "python" else "base ok", ""

    fake = make_runner(handler)
    report = replay_receipt(receipt, repo, lambda image: fake)

    assert report.overall == "reproduced"
    assert seen == [(True, "python", True), (False, "pytest", False)]
    assert fake.calls[0][1][0] == "python"


def test_replay_reports_divergence(scenario, make_runner, tmp_path) -> None:
    repo, shas = scenario
    receipt = _signed(tmp_path, shas, [_command("head"), _command("base")])
    fake = make_runner(lambda workdir, argv: (1, "", "") if "lib.py" else (0, "", ""))
    report = replay_receipt(receipt, repo, lambda image: fake)

    assert report.overall == "diverged"
    assert report.results[0].status == "diverged"
    assert "exit 0 originally, exit 1 on replay" in report.results[0].detail
    assert report.as_dict()["diverged"] == 2


def test_replay_reports_timeout_divergence(scenario, make_runner, tmp_path) -> None:
    repo, shas = scenario
    receipt = _signed(tmp_path, shas, [_command("head", exit_code=None, timed_out=True)])
    fake = make_runner(lambda workdir, argv: (0, "", ""))
    report = replay_receipt(receipt, repo, lambda image: fake)
    assert report.results[0].status == "diverged"
    assert "timed out originally" in report.results[0].detail


def test_durations_in_output_are_ignored(scenario, make_runner, tmp_path) -> None:
    repo, shas = scenario
    receipt = _signed(
        tmp_path, shas, [_command("head", stdout="Ran 1 test in 0.001s\n\nOK", stderr="at 0x7f1")]
    )
    fake = make_runner(lambda workdir, argv: (0, "Ran 1 test in 0.512s\n\nOK", "at 0x9ab"))
    report = replay_receipt(receipt, repo, lambda image: fake)
    assert report.overall == "reproduced"
    assert report.results[0].status == "reproduced"


def test_different_output_is_reported_but_does_not_diverge(scenario, make_runner, tmp_path) -> None:
    repo, shas = scenario
    receipt = _signed(tmp_path, shas, [_command("head", stdout="one")])
    fake = make_runner(lambda workdir, argv: (0, "two", ""))
    report = replay_receipt(receipt, repo, lambda image: fake)
    assert report.overall == "reproduced"
    assert report.results[0].status == "output_differs"
    assert report.as_dict()["output_differs"] == 1
    assert report.as_dict()["issues"] == []


def test_version_1_receipt_is_incomplete(scenario, make_runner, tmp_path) -> None:
    repo, shas = scenario
    command = _command(None, timeout_s=None)
    receipt = _signed(tmp_path, shas, [command], version=1)
    fake = make_runner(lambda workdir, argv: (0, "", ""))
    report = replay_receipt(receipt, repo, lambda image: fake)

    assert report.overall == "incomplete"
    assert report.results[0].status == "skipped"
    assert "version 2" in report.results[0].detail
    assert fake.calls == []


def test_missing_and_mismatched_artifacts_are_skipped(scenario, make_runner, tmp_path) -> None:
    repo, shas = scenario
    missing = _command("head", overlay={"a.py": "a" * 64})
    wrong = _command("head", overlay={"b.py": "b" * 64})
    receipt = _signed(tmp_path, shas, [missing, wrong], {"b" * 64: "not what the digest says"})
    fake = make_runner(lambda workdir, argv: (0, "", ""))
    report = replay_receipt(receipt, repo, lambda image: fake)

    assert report.overall == "incomplete"
    assert "was not stored" in report.results[0].detail
    assert "does not match its digest" in report.results[1].detail
    assert fake.calls == []


@pytest.mark.parametrize("path", ["../evil.py", "/etc/evil.py", "a/../../evil.py", ""])
def test_unsafe_artifact_paths_are_skipped(path, scenario, make_runner, tmp_path) -> None:
    repo, shas = scenario
    command = _command("head", overlay={path: _sha("x")})
    receipt = _signed(tmp_path, shas, [command], {_sha("x"): "x"})
    fake = make_runner(lambda workdir, argv: (0, "", ""))
    report = replay_receipt(receipt, repo, lambda image: fake)

    assert report.results[0].status == "skipped"
    assert fake.calls == []
    assert not (tmp_path / "evil.py").exists()


def test_tampered_receipt_is_refused(scenario, make_runner, tmp_path) -> None:
    repo, shas = scenario
    receipt = _signed(tmp_path, shas, [_command("head")])
    receipt.body.verdict = Verdict.FAIL
    fake = make_runner(lambda workdir, argv: (0, "", ""))
    with pytest.raises(ReplayError, match="verification"):
        replay_receipt(receipt, repo, lambda image: fake)


def test_receipt_without_commands_is_empty(scenario, make_runner, tmp_path) -> None:
    repo, shas = scenario
    receipt = _signed(tmp_path, shas, [])
    report = replay_receipt(receipt, repo, lambda image: make_runner(lambda w, a: (0, "", "")))
    assert report.overall == "empty"


def test_unknown_commit_is_an_error(make_repo, make_runner, tmp_path) -> None:
    repo, _ = make_repo([{"a.txt": "x\n"}])
    receipt = _signed(tmp_path, ["f" * 40, "e" * 40], [_command("head")])
    with pytest.raises(ReplayError, match="head commit"):
        replay_receipt(receipt, repo, lambda image: make_runner(lambda w, a: (0, "", "")))


def test_overlay_restores_files_and_removes_new_ones(tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_text("old")
    with _overlaid(tmp_path, {"a.txt": "new", "pkg/sub/b.txt": "b"}):
        assert (tmp_path / "a.txt").read_text() == "new"
        assert (tmp_path / "pkg" / "sub" / "b.txt").read_text() == "b"
    assert (tmp_path / "a.txt").read_text() == "old"
    assert not (tmp_path / "pkg").exists()


def test_overlay_cleans_up_when_a_later_path_is_unsafe(tmp_path: Path) -> None:
    with pytest.raises(ReplayError):
        with _overlaid(tmp_path, {"ok.txt": "x", "../bad.txt": "y"}):
            pass
    assert not (tmp_path / "ok.txt").exists()


def test_safe_target_stays_inside_the_root(tmp_path: Path) -> None:
    assert _safe_target(tmp_path, "a/b.py") == (tmp_path / "a" / "b.py").resolve()
    for bad in ("..", "a/../..", "/abs", "a\\b"):
        with pytest.raises(ReplayError):
            _safe_target(tmp_path, bad)


def test_factory_for_a_plain_runner_returns_it(make_runner) -> None:
    fake = make_runner(lambda workdir, argv: (0, "", ""))
    factory = runner_factory_from(fake)
    assert factory("img-a") is fake
    assert factory("img-b") is fake


@pytest.fixture
def isolated(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.chdir(tmp_path)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_cli_replay_reproduced(scenario, make_runner, tmp_path, monkeypatch, isolated) -> None:
    repo, shas = scenario
    receipt = _signed(tmp_path, shas, [_command("head", stdout="ok")])
    path = tmp_path / "receipt.json"
    path.write_text(receipt.model_dump_json())
    fake = make_runner(lambda workdir, argv: (0, "ok", ""))
    monkeypatch.setattr(cli, "_replay_runner_factory", lambda: lambda image: fake)

    result = cli_runner.invoke(cli.app, ["replay", str(path), "--repo-path", str(repo)])
    assert result.exit_code == 0
    assert "REPRODUCED" in result.output

    as_json = cli_runner.invoke(cli.app, ["replay", str(path), "--repo-path", str(repo), "--json"])
    assert as_json.exit_code == 0
    assert '"overall": "reproduced"' in as_json.output


def test_cli_replay_diverged(scenario, make_runner, tmp_path, monkeypatch, isolated) -> None:
    repo, shas = scenario
    receipt = _signed(tmp_path, shas, [_command("head")])
    path = tmp_path / "receipt.json"
    path.write_text(receipt.model_dump_json())
    fake = make_runner(lambda workdir, argv: (1, "", ""))
    monkeypatch.setattr(cli, "_replay_runner_factory", lambda: lambda image: fake)

    result = cli_runner.invoke(cli.app, ["replay", str(path), "--repo-path", str(repo)])
    assert result.exit_code == 1
    assert "DIVERGED" in result.output
    assert "[0] diverged" in result.output


def test_cli_replay_needs_a_repository(scenario, tmp_path, isolated) -> None:
    _, shas = scenario
    receipt = _signed(tmp_path, shas, [_command("head")])
    path = tmp_path / "receipt.json"
    path.write_text(receipt.model_dump_json())

    result = cli_runner.invoke(cli.app, ["replay", str(path)])
    assert result.exit_code == 3
    assert "--repo-path" in result.output


@pytest.mark.docker
@needs_docker
def test_replay_in_a_real_sandbox(make_repo, tmp_path: Path) -> None:
    repo, shas = make_repo([{"a.txt": "one\n"}, {"a.txt": "two\n"}])
    sandbox = SandboxRunner(SandboxPolicy(image="python:3.12-slim", timeout_s=60))
    sandbox.ensure_image()

    extra = "from overlay\n"
    argv = ["python", "-c", "print(open('a.txt').read().strip(), open('extra.txt').read().strip())"]
    with workspace(repo, shas[1]) as head_dir:
        (head_dir / "extra.txt").write_text(extra)
        original = sandbox.run(head_dir, argv, timeout_s=60)
    assert original.stdout == "two from overlay\n"

    command = original.model_copy(update={"side": "head", "overlay": {"extra.txt": _sha(extra)}})
    receipt = _signed(tmp_path, shas, [command], {_sha(extra): extra})
    report = replay_receipt(receipt, repo, runner_factory_from(sandbox))

    assert report.overall == "reproduced"
    assert report.results[0].status == "reproduced"
