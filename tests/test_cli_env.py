import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from typer.testing import CliRunner

from tribunal import cli
from tribunal.config import get_settings
from tribunal.envbuild import EnvBuildError, Environment
from tribunal.models import ReceiptBody, Verdict
from tribunal.receipts import ReceiptSigner

cli_runner = CliRunner()
IMAGE = "tribunal-env:abc123def456"
ENV_VARS = (
    "TRIBUNAL_BUILD_ENV",
    "TRIBUNAL_ALLOW_SDIST",
    "TRIBUNAL_SANDBOX_IMAGE",
    "TRIBUNAL_COMMENT",
    "TRIBUNAL_FAIL_ON",
    "TRIBUNAL_TEST_COMMAND",
    "TRIBUNAL_AGENT",
    "TRIBUNAL_RECEIPT_OUT",
    "GITHUB_STEP_SUMMARY",
    "GITHUB_OUTPUT",
    "GITHUB_TOKEN",
)


@pytest.fixture(autouse=True)
def isolated(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.chdir(tmp_path)
    for name in ENV_VARS:
        monkeypatch.delenv(name, raising=False)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _environment(image: str = IMAGE, status: str = "built") -> Environment:
    return Environment(
        image=image,
        status=status,
        base_image="python:3.12-slim",
        requirements=("a==1", "b>=2"),
        skipped=("requirements.txt: -e .",),
        sources=("requirements.txt",),
        unpinned=1,
    )


def _stub_pipeline(tmp_path: Path) -> SimpleNamespace:
    signer = ReceiptSigner.load_or_create(tmp_path / "k.pem")
    receipt = signer.sign(
        ReceiptBody(
            submission_id="sub_x",
            repo="o/r",
            base_sha="a" * 40,
            head_sha="b" * 40,
            verdict=Verdict.PASS,
            rationale="ok",
        )
    )
    return SimpleNamespace(
        submit=lambda **kwargs: SimpleNamespace(id="sub_x"),
        run=lambda submission_id: receipt,
    )


def _event(tmp_path: Path, base: str, head: str) -> Path:
    payload = {
        "repository": {"full_name": "o/r"},
        "pull_request": {
            "number": 7,
            "title": "Fix",
            "body": "Fixes it.",
            "base": {"sha": base},
            "head": {"sha": head},
            "user": {"login": "bot"},
        },
    }
    path = tmp_path / "event.json"
    path.write_text(json.dumps(payload))
    return path


def test_build_image_prints_the_image_and_passes_every_option(monkeypatch) -> None:
    seen: dict = {}

    def fake(repo_path, ref, **kwargs):
        seen.update(ref=ref, **kwargs)
        return _environment()

    monkeypatch.setattr(cli, "build_environment", fake)
    result = cli_runner.invoke(
        cli.app,
        [
            "build-image",
            "--ref",
            "abc",
            "--extra",
            "test",
            "--group",
            "dev",
            "--requirements",
            "requirements.txt",
            "--allow-sdist",
            "--force",
        ],
    )

    assert result.exit_code == 0
    assert f"TRIBUNAL_SANDBOX_IMAGE={IMAGE}" in result.output
    assert "unpinned dependencies: 1" in result.output
    assert "skipped: requirements.txt: -e ." in result.output
    assert seen == {
        "ref": "abc",
        "base_image": "python:3.12-slim",
        "requirements_files": ["requirements.txt"],
        "extras": ["test"],
        "groups": ["dev"],
        "allow_sdist": True,
        "force": True,
    }


def test_build_image_json_and_errors(monkeypatch) -> None:
    monkeypatch.setattr(cli, "build_environment", lambda repo_path, ref, **kw: _environment())
    result = cli_runner.invoke(cli.app, ["build-image", "--json"])
    assert result.exit_code == 0
    assert json.loads(result.stdout)["image"] == IMAGE

    def boom(repo_path, ref, **kwargs):
        raise EnvBuildError("boom")

    monkeypatch.setattr(cli, "build_environment", boom)
    failed = cli_runner.invoke(cli.app, ["build-image"])
    assert failed.exit_code == 3
    assert "error: boom" in failed.output


def test_a_built_image_is_never_used_as_a_base(monkeypatch) -> None:
    monkeypatch.setenv("TRIBUNAL_SANDBOX_IMAGE", IMAGE)
    get_settings.cache_clear()
    seen: dict = {}
    monkeypatch.setattr(
        cli,
        "build_environment",
        lambda repo_path, ref, **kw: seen.update(kw) or _environment(),
    )
    cli_runner.invoke(cli.app, ["build-image"])
    assert seen["base_image"] == "python:3.12-slim"


def test_submit_build_env_runs_in_the_built_image(tmp_path: Path, monkeypatch) -> None:
    built: dict = {}
    captured: dict = {}
    monkeypatch.setattr(
        cli,
        "build_environment",
        lambda repo_path, ref, **kw: built.update(ref=ref, **kw) or _environment(),
    )
    monkeypatch.setattr(
        cli,
        "build_pipeline",
        lambda **options: captured.update(options) or _stub_pipeline(tmp_path),
    )

    result = cli_runner.invoke(
        cli.app, ["submit", "--repo-path", str(tmp_path), "--base", "main~1", "--build-env"]
    )

    assert result.exit_code == 0
    assert built["ref"] == "main~1"
    assert built["base_image"] == "python:3.12-slim"
    assert built["allow_sdist"] is False
    assert captured["settings"].sandbox_image == IMAGE
    assert f"environment: {IMAGE} (built)" in result.output


def test_submit_image_skips_the_build(tmp_path: Path, monkeypatch) -> None:
    captured: dict = {}

    def must_not_build(repo_path, ref, **kwargs):
        raise AssertionError("no build expected")

    monkeypatch.setattr(cli, "build_environment", must_not_build)
    monkeypatch.setattr(
        cli,
        "build_pipeline",
        lambda **options: captured.update(options) or _stub_pipeline(tmp_path),
    )
    result = cli_runner.invoke(cli.app, ["submit", "--repo-path", str(tmp_path), "--image", "x:1"])
    assert result.exit_code == 0
    assert captured["settings"].sandbox_image == "x:1"


def test_submit_without_options_keeps_the_default_settings(tmp_path: Path, monkeypatch) -> None:
    captured: dict = {"untouched": True}
    monkeypatch.setattr(
        cli,
        "build_pipeline",
        lambda **options: captured.update(options) or _stub_pipeline(tmp_path),
    )
    result = cli_runner.invoke(cli.app, ["submit", "--repo-path", str(tmp_path)])
    assert result.exit_code == 0
    assert captured == {"untouched": True}


def test_submit_rejects_image_with_build_env(tmp_path: Path) -> None:
    result = cli_runner.invoke(
        cli.app,
        ["submit", "--repo-path", str(tmp_path), "--image", "x:1", "--build-env"],
    )
    assert result.exit_code == 3
    assert "either --image or --build-env" in result.output


def _run_ci(scenario, tmp_path: Path, monkeypatch, extra_args: list[str]):
    repo, shas = scenario
    monkeypatch.setenv("GITHUB_EVENT_PATH", str(_event(tmp_path, shas[0], shas[1])))
    built: dict = {}
    captured: dict = {}
    monkeypatch.setattr(
        cli,
        "build_environment",
        lambda repo_path, ref, **kw: built.update(ref=ref, **kw) or _environment(),
    )
    monkeypatch.setattr(
        cli,
        "build_pipeline",
        lambda **options: captured.update(options) or _stub_pipeline(tmp_path),
    )
    result = cli_runner.invoke(
        cli.app, ["ci", "--repo-path", str(repo), "--no-comment", *extra_args]
    )
    return result, built, captured, shas


def test_ci_builds_the_environment_from_the_merge_base(scenario, tmp_path, monkeypatch) -> None:
    result, built, captured, shas = _run_ci(
        scenario, tmp_path, monkeypatch, ["--build-env", "--allow-sdist"]
    )
    assert result.exit_code == 0
    assert built["ref"] == shas[0]
    assert built["allow_sdist"] is True
    assert captured["settings"].sandbox_image == IMAGE


def test_ci_reads_the_build_flags_from_the_environment(scenario, tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("TRIBUNAL_BUILD_ENV", "true")
    monkeypatch.setenv("TRIBUNAL_ALLOW_SDIST", "false")
    result, built, captured, _ = _run_ci(scenario, tmp_path, monkeypatch, [])
    assert result.exit_code == 0
    assert built["allow_sdist"] is False
    assert captured["settings"].sandbox_image == IMAGE


def test_ci_does_not_build_unless_asked(scenario, tmp_path, monkeypatch) -> None:
    result, built, captured, _ = _run_ci(scenario, tmp_path, monkeypatch, [])
    assert result.exit_code == 0
    assert built == {}
    assert captured == {}
