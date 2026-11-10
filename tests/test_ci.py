import json
from pathlib import Path

import httpx
import pytest
from typer.testing import CliRunner

from tribunal import cli
from tribunal.ci import (
    MARKER,
    CIError,
    load_pr_context,
    upsert_comment,
    write_outputs,
    write_step_summary,
)
from tribunal.llm import ScriptedLLM
from tribunal.models import ReceiptBody, SignedReceipt, Verdict
from tribunal.receipts import ReceiptSigner

runner = CliRunner()


def _event(
    tmp_path: Path,
    base: str,
    head: str,
    title: str | None = "Fix",
    body: str | None = "Fixes it.",
) -> Path:
    payload = {
        "repository": {"full_name": "o/r"},
        "pull_request": {
            "number": 7,
            "title": title,
            "body": body,
            "base": {"sha": base},
            "head": {"sha": head},
            "user": {"login": "codex-bot"},
        },
    }
    path = tmp_path / "event.json"
    path.write_text(json.dumps(payload))
    return path


def _receipt(tmp_path: Path) -> SignedReceipt:
    signer = ReceiptSigner.load_or_create(tmp_path / "k.pem")
    return signer.sign(
        ReceiptBody(
            submission_id="sub_x",
            repo="o/r",
            base_sha="a" * 40,
            head_sha="b" * 40,
            verdict=Verdict.PASS,
            rationale="ok",
        )
    )


def test_load_pr_context(tmp_path: Path) -> None:
    context = load_pr_context(_event(tmp_path, "a" * 40, "b" * 40))
    assert context.repo == "o/r"
    assert context.number == 7
    assert context.base_sha == "a" * 40
    assert context.head_sha == "b" * 40
    assert context.title == "Fix"
    assert context.author == "codex-bot"


def test_null_title_and_body_become_empty(tmp_path: Path) -> None:
    context = load_pr_context(_event(tmp_path, "a" * 40, "b" * 40, title=None, body=None))
    assert context.title == ""
    assert context.body == ""


def test_non_pr_event_rejected(tmp_path: Path) -> None:
    path = tmp_path / "push.json"
    path.write_text(json.dumps({"ref": "refs/heads/main"}))
    with pytest.raises(CIError):
        load_pr_context(path)


def test_bad_payloads_rejected(tmp_path: Path) -> None:
    with pytest.raises(CIError):
        load_pr_context(tmp_path / "missing.json")
    broken = tmp_path / "broken.json"
    broken.write_text(json.dumps({"pull_request": {"number": 1}}))
    with pytest.raises(CIError):
        load_pr_context(broken)


def test_step_summary_appends(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    target = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(target))
    assert write_step_summary("one")
    assert write_step_summary("two")
    assert target.read_text() == "one\ntwo\n"


def test_step_summary_without_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    assert not write_step_summary("x")


def test_outputs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    target = tmp_path / "output.txt"
    monkeypatch.setenv("GITHUB_OUTPUT", str(target))
    receipt = _receipt(tmp_path)
    assert write_outputs(receipt)
    lines = dict(line.split("=", 1) for line in target.read_text().splitlines())
    assert lines == {
        "verdict": "pass",
        "receipt-id": receipt.body.receipt_id,
        "digest": receipt.digest,
        "head-sha": "b" * 40,
    }


def _client(handler) -> httpx.Client:
    return httpx.Client(
        base_url="https://api.github.com",
        transport=httpx.MockTransport(handler),
    )


def test_comment_created_when_absent() -> None:
    seen: list[tuple[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append((request.method, request.url.path))
        if request.method == "GET":
            return httpx.Response(200, json=[{"id": 1, "body": "other", "user": {"type": "User"}}])
        return httpx.Response(201, json={"html_url": "https://example.test/c/9"})

    url = upsert_comment("o/r", 7, "tok", "hello", client=_client(handler))
    assert url == "https://example.test/c/9"
    assert seen == [
        ("GET", "/repos/o/r/issues/7/comments"),
        ("POST", "/repos/o/r/issues/7/comments"),
    ]


def test_comment_updated_when_present() -> None:
    bodies: list[str] = []
    seen: list[tuple[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append((request.method, request.url.path))
        if request.method == "GET":
            old = {"id": 5, "body": f"{MARKER}\nold", "user": {"type": "Bot"}}
            return httpx.Response(200, json=[old])
        bodies.append(json.loads(request.content)["body"])
        return httpx.Response(200, json={"html_url": "https://example.test/c/5"})

    url = upsert_comment("o/r", 7, "tok", "fresh", client=_client(handler))
    assert url == "https://example.test/c/5"
    assert seen[-1] == ("PATCH", "/repos/o/r/issues/comments/5")
    assert bodies[0].startswith(MARKER)
    assert "fresh" in bodies[0]


def test_marker_from_non_bot_is_ignored() -> None:
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.method)
        if request.method == "GET":
            spoof = {"id": 5, "body": f"{MARKER}\nspoof", "user": {"type": "User"}}
            return httpx.Response(200, json=[spoof])
        return httpx.Response(201, json={"html_url": "https://example.test/c/9"})

    upsert_comment("o/r", 7, "tok", "hello", client=_client(handler))
    assert seen == ["GET", "POST"]


def test_http_errors_become_ci_errors() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, json={"message": "forbidden"})

    with pytest.raises(CIError):
        upsert_comment("o/r", 7, "tok", "hello", client=_client(handler))


@pytest.fixture
def ci_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path]:
    summary = tmp_path / "summary.md"
    output = tmp_path / "output.txt"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    monkeypatch.setenv("GITHUB_OUTPUT", str(output))
    for name in (
        "GITHUB_TOKEN",
        "TRIBUNAL_TEST_COMMAND",
        "TRIBUNAL_AGENT",
        "TRIBUNAL_COMMENT",
        "TRIBUNAL_FAIL_ON",
        "TRIBUNAL_RECEIPT_OUT",
    ):
        monkeypatch.delenv(name, raising=False)
    return summary, output


def test_ci_pass(
    scenario, make_runner, make_pipeline, probes_json, ci_env, tmp_path, monkeypatch
) -> None:
    repo, shas = scenario
    summary, output = ci_env
    monkeypatch.setenv("GITHUB_EVENT_PATH", str(_event(tmp_path, shas[0], shas[1])))
    llm = ScriptedLLM([json.dumps({"claims": []}), probes_json])
    pipe = make_pipeline(make_runner(lambda workdir, argv: (0, "ok", "")), llm)
    monkeypatch.setattr(cli, "build_pipeline", lambda: pipe)
    receipt_path = tmp_path / "out" / "receipt.json"

    result = runner.invoke(
        cli.app,
        ["ci", "--repo-path", str(repo), "--no-comment", "--receipt-out", str(receipt_path)],
    )

    assert result.exit_code == 0
    assert "Tribunal: PASS" in summary.read_text()
    assert "verdict=pass" in output.read_text()
    saved = SignedReceipt.model_validate_json(receipt_path.read_text())
    assert saved.body.head_sha == shas[1]
    assert saved.body.repo == "o/r"


@pytest.mark.parametrize(("fail_on", "expected"), [("fail", 0), ("inconclusive", 2)])
def test_ci_inconclusive_exit_codes(
    scenario, make_runner, make_pipeline, ci_env, tmp_path, monkeypatch, fail_on, expected
) -> None:
    repo, shas = scenario
    monkeypatch.setenv("GITHUB_EVENT_PATH", str(_event(tmp_path, shas[0], shas[1])))
    pipe = make_pipeline(make_runner(lambda workdir, argv: (0, "ok", "")), ScriptedLLM([]))
    monkeypatch.setattr(cli, "build_pipeline", lambda: pipe)

    result = runner.invoke(
        cli.app,
        ["ci", "--repo-path", str(repo), "--no-comment", "--fail-on", fail_on],
    )
    assert result.exit_code == expected
    assert "INCONCLUSIVE" in result.output


def test_ci_posts_comment(
    scenario, make_runner, make_pipeline, probes_json, ci_env, tmp_path, monkeypatch
) -> None:
    repo, shas = scenario
    monkeypatch.setenv("GITHUB_EVENT_PATH", str(_event(tmp_path, shas[0], shas[1])))
    monkeypatch.setenv("GITHUB_TOKEN", "tok")
    llm = ScriptedLLM([json.dumps({"claims": []}), probes_json])
    pipe = make_pipeline(make_runner(lambda workdir, argv: (0, "ok", "")), llm)
    monkeypatch.setattr(cli, "build_pipeline", lambda: pipe)
    posted: list[tuple[str, int, str, str]] = []

    def fake_upsert(repo_name: str, number: int, token: str, markdown: str) -> str:
        posted.append((repo_name, number, token, markdown))
        return "https://example.test/c/1"

    monkeypatch.setattr(cli, "upsert_comment", fake_upsert)

    result = runner.invoke(cli.app, ["ci", "--repo-path", str(repo)])

    assert result.exit_code == 0
    assert len(posted) == 1
    assert posted[0][:3] == ("o/r", 7, "tok")
    assert "Tribunal" in posted[0][3]


def test_ci_requires_github_event(ci_env, monkeypatch) -> None:
    monkeypatch.delenv("GITHUB_EVENT_PATH", raising=False)
    result = runner.invoke(cli.app, ["ci"])
    assert result.exit_code == 3
    assert "GITHUB_EVENT_PATH" in result.output


def test_ci_rejects_bad_fail_on(ci_env) -> None:
    result = runner.invoke(cli.app, ["ci", "--fail-on", "nope"])
    assert result.exit_code == 3
    assert "--fail-on" in result.output
