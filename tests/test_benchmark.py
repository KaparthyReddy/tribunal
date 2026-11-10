import subprocess
import sys
from pathlib import Path

import pytest

from benchmark.baseline import review
from benchmark.cases import ALL_CASES
from benchmark.metrics import score
from benchmark.model import build_repo
from benchmark.report import headline_markdown, render_html, render_markdown, verdict_class
from benchmark.run import evaluate, select_cases
from tribunal.llm import LLMError, ScriptedLLM
from tribunal.sandbox import materialize


def _unittest_exit_code(directory: Path) -> int:
    result = subprocess.run(
        [sys.executable, "-m", "unittest"],
        cwd=directory,
        capture_output=True,
        text=True,
        timeout=60,
    )
    return result.returncode


def test_case_inventory() -> None:
    ids = [case.id for case in ALL_CASES]
    assert len(ids) == len(set(ids)) == 20
    assert sum(1 for case in ALL_CASES if case.expect == "buggy") == 13
    assert sum(1 for case in ALL_CASES if case.expect == "clean") == 7
    assert {case.category for case in ALL_CASES} == {
        "regression",
        "untested",
        "false-claim",
        "clean",
    }


@pytest.mark.parametrize("case", ALL_CASES, ids=lambda case: case.id)
def test_case_behaves_as_declared(case, tmp_path: Path) -> None:
    repo, base_sha, head_sha = build_repo(case, tmp_path / "repos")
    base_dir = tmp_path / "base"
    head_dir = tmp_path / "head"
    materialize(repo, base_sha, base_dir)
    materialize(repo, head_sha, head_dir)

    assert _unittest_exit_code(base_dir) == 0
    head_code = _unittest_exit_code(head_dir)
    if case.tests_catch:
        assert head_code != 0
    else:
        assert head_code == 0


def test_build_repo_has_two_commits(tmp_path: Path) -> None:
    repo, base_sha, head_sha = build_repo(ALL_CASES[0], tmp_path)
    assert base_sha != head_sha
    assert (repo / "seq.py").exists()


def test_select_cases() -> None:
    assert len(select_cases(None)) == 20
    assert [c.id for c in select_cases("clean-rename, regress-ratio")] == [
        "clean-rename",
        "regress-ratio",
    ]
    with pytest.raises(ValueError, match="nope"):
        select_cases("nope")


def test_review_parses_decisions() -> None:
    llm = ScriptedLLM(
        [
            '{"decision": "reject", "reason": "bug"}',
            '{"decision": "APPROVE", "reason": "ok"}',
        ]
    )
    rejected = review(llm, "t", "d", "diff")
    approved = review(llm, "t", "d", "diff")
    assert (rejected.outcome, rejected.reason) == ("fail", "bug")
    assert approved.outcome == "pass"


def test_review_rejects_garbage() -> None:
    with pytest.raises(LLMError):
        review(ScriptedLLM(['{"decision": "maybe"}']), "t", "d", "diff")
    with pytest.raises(LLMError):
        review(ScriptedLLM(["[1, 2]"]), "t", "d", "diff")


def _row(expect: str, tribunal: str | None = None, baseline: str | None = None) -> dict:
    row: dict = {"id": "x", "category": "c", "expect": expect, "title": "t", "note": ""}
    if tribunal is not None:
        row["tribunal"] = {"outcome": tribunal}
    if baseline is not None:
        row["baseline"] = {"outcome": baseline}
    return row


def test_score_counts_and_rates() -> None:
    cases = [
        _row("buggy", tribunal="fail"),
        _row("buggy", tribunal="inconclusive"),
        _row("buggy", tribunal="pass"),
        _row("clean", tribunal="pass"),
        _row("clean", tribunal="fail"),
        _row("clean", tribunal="error"),
    ]
    result = score(cases, "tribunal")
    assert result["errors"] == 1
    assert result["buggy"] == {
        "n": 3,
        "caught": 1,
        "flagged": 1,
        "missed": 1,
        "catch_rate": 1 / 3,
        "flag_rate": 2 / 3,
        "false_green_rate": 1 / 3,
    }
    assert result["clean"]["n"] == 2
    assert result["clean"]["blocked"] == 1
    assert result["clean"]["false_block_rate"] == 0.5


def test_score_empty_system() -> None:
    result = score([_row("buggy", tribunal="fail")], "baseline")
    assert result["buggy"]["n"] == 0
    assert result["buggy"]["catch_rate"] is None


def test_evaluate_with_fake_systems(tmp_path: Path) -> None:
    seen: list[str] = []

    def fake(case, repo, base, head):
        seen.append(case.id)
        assert (repo / next(iter(case.base))).exists()
        return {"outcome": "pass"}

    def broken(case, repo, base, head):
        raise RuntimeError("boom")

    calls: list[int] = []
    rows = evaluate(
        ALL_CASES[:2],
        tmp_path,
        tribunal=fake,
        baseline=broken,
        progress=lambda index, total, rows: calls.append(index),
    )
    assert seen == [ALL_CASES[0].id, ALL_CASES[1].id]
    assert calls == [1, 2]
    assert rows[0]["tribunal"]["outcome"] == "pass"
    assert rows[0]["baseline"]["outcome"] == "error"
    assert "boom" in rows[0]["baseline"]["error"]
    assert "seconds" in rows[0]["tribunal"]


def test_verdict_class() -> None:
    assert verdict_class("buggy", "fail") == "good"
    assert verdict_class("buggy", "pass") == "bad"
    assert verdict_class("clean", "pass") == "good"
    assert verdict_class("clean", "fail") == "bad"
    assert verdict_class("buggy", "inconclusive") == "warn"
    assert verdict_class("clean", "error") == "muted"
    assert verdict_class("clean", None) == "muted"


def _results() -> dict:
    rows = [
        _row("buggy", tribunal="fail", baseline="pass"),
        _row("clean", tribunal="pass", baseline="fail"),
    ]
    rows[0]["title"] = "<script>alert(1)</script>"
    rows[0]["tribunal"]["findings"] = [{"severity": "high", "title": "<b>bad</b>"}]
    rows[0]["tribunal"]["rationale"] = "because <i>reasons</i>"
    return {
        "meta": {"provider": "ollama", "model": "m", "sandbox_image": "img", "cases_total": 2},
        "cases": rows,
    }


def test_reports_render() -> None:
    results = _results()

    table = headline_markdown(results)
    assert "Tribunal" in table
    assert "LLM review" in table
    assert "1/1 (100%)" in table

    markdown = render_markdown(results)
    assert markdown.startswith("# Tribunal benchmark")
    assert "| x | c | buggy | fail | pass |" in markdown

    page = render_html(results)
    assert "<script>alert" not in page
    assert "&lt;script&gt;" in page
    assert "<b>bad</b>" not in page
    assert "&lt;b&gt;bad&lt;/b&gt;" in page
    assert 'class="good"' in page
    assert 'class="bad"' in page


def test_headline_without_results() -> None:
    assert headline_markdown({"cases": []}) == "No results."
