import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from tribunal import cli
from tribunal.config import get_settings
from tribunal.llm import ScriptedLLM
from tribunal.models import ReceiptBody, Verdict
from tribunal.receipts import ReceiptSigner

runner = CliRunner()


@pytest.fixture(autouse=True)
def isolated(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.chdir(tmp_path)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _receipt_file(tmp_path: Path) -> Path:
    signer = ReceiptSigner.load_or_create(tmp_path / "other.pem")
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
    path = tmp_path / "receipt.json"
    path.write_text(receipt.model_dump_json())
    return path


def test_submit_pass(scenario, make_runner, make_pipeline, probes_json, monkeypatch) -> None:
    repo, shas = scenario
    pipe = make_pipeline(
        make_runner(lambda workdir, argv: (0, "ok", "")), ScriptedLLM([probes_json])
    )
    monkeypatch.setattr(cli, "build_pipeline", lambda: pipe)

    result = runner.invoke(
        cli.app,
        ["submit", "--repo-path", str(repo), "--base", shas[0], "--head", shas[1], "--agent", "x"],
    )
    assert result.exit_code == 0
    assert "VERDICT: PASS" in result.output


def test_submit_json_and_fail_exit_code(
    scenario, make_runner, make_pipeline, probes_json, is_head, monkeypatch
) -> None:
    repo, shas = scenario
    pipe = make_pipeline(
        make_runner(lambda workdir, argv: (1, "F", "") if is_head(workdir) else (0, "", "")),
        ScriptedLLM([probes_json]),
    )
    monkeypatch.setattr(cli, "build_pipeline", lambda: pipe)

    result = runner.invoke(
        cli.app,
        [
            "submit",
            "--repo-path",
            str(repo),
            "--base",
            shas[0],
            "--head",
            shas[1],
            "--test-cmd",
            "pytest -q",
            "--json",
        ],
    )
    assert result.exit_code == 1
    assert json.loads(result.stdout)["body"]["verdict"] == "fail"


def test_submit_error_exit_code(scenario, make_runner, make_pipeline, monkeypatch) -> None:
    repo, shas = scenario
    pipe = make_pipeline(make_runner(lambda workdir, argv: (0, "", "")), ScriptedLLM([]))
    monkeypatch.setattr(cli, "build_pipeline", lambda: pipe)

    result = runner.invoke(
        cli.app, ["submit", "--repo-path", str(repo), "--base", "nope", "--head", shas[1]]
    )
    assert result.exit_code == 3
    assert "error:" in result.output


def test_verify_receipt_file(tmp_path: Path) -> None:
    path = _receipt_file(tmp_path)
    result = runner.invoke(cli.app, ["verify-receipt", str(path)])
    assert result.exit_code == 0
    assert "integrity: valid" in result.output

    data = json.loads(path.read_text())
    data["body"]["verdict"] = "fail"
    path.write_text(json.dumps(data))
    tampered = runner.invoke(cli.app, ["verify-receipt", str(path)])
    assert tampered.exit_code == 1
    assert "INVALID" in tampered.output


def test_verify_receipt_wrong_expected_key(tmp_path: Path) -> None:
    path = _receipt_file(tmp_path)
    result = runner.invoke(cli.app, ["verify-receipt", str(path), "--public-key", "AAAA"])
    assert result.exit_code == 1
    assert "DIFFERENT" in result.output


def test_verify_unknown_receipt() -> None:
    result = runner.invoke(cli.app, ["verify-receipt", "rcp_missing"])
    assert result.exit_code == 3


def test_public_key_is_stable() -> None:
    first = runner.invoke(cli.app, ["public-key"])
    second = runner.invoke(cli.app, ["public-key"])
    assert first.exit_code == 0
    assert first.output.strip() == second.output.strip()
    assert first.output.strip()


def test_trust_command() -> None:
    result = runner.invoke(cli.app, ["trust", "codex"])
    assert result.exit_code == 0
    assert json.loads(result.stdout)["scrutiny"] == "standard"
