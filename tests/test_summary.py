from pathlib import Path

from tribunal.models import (
    Claim,
    ClaimResult,
    ClaimStatus,
    Finding,
    ReceiptBody,
    Severity,
    Verdict,
)
from tribunal.receipts import ReceiptSigner
from tribunal.summary import render_markdown, render_text, summarize


def _receipt(tmp_path: Path):
    body = ReceiptBody(
        submission_id="sub_x",
        repo="o/r",
        base_sha="a" * 40,
        head_sha="b" * 40,
        verdict=Verdict.FAIL,
        rationale="1 blocking issue(s):\n- boom",
        claims=[
            Claim(id="c1", text="fixes | it"),
            Claim(id="c2", text="no change"),
        ],
        claim_results=[ClaimResult(claim_id="c1", status=ClaimStatus.REFUTED)],
        findings=[
            Finding(source="a", title="low one", severity=Severity.LOW),
            Finding(source="b", title="high one", severity=Severity.HIGH),
        ],
    )
    return ReceiptSigner.load_or_create(tmp_path / "k.pem").sign(body)


def test_summarize(tmp_path: Path) -> None:
    summary = summarize(_receipt(tmp_path), max_findings=1)
    assert summary["verdict"] == "fail"
    assert summary["findings"] == [{"source": "b", "title": "high one", "severity": "high"}]
    assert summary["findings_total"] == 2
    assert [c["status"] for c in summary["claims"]] == ["refuted", "unverifiable"]


def test_render_text(tmp_path: Path) -> None:
    text = render_text(_receipt(tmp_path))
    assert text.startswith("VERDICT: FAIL")
    assert "[high] b: high one" in text
    assert text.index("high one") < text.index("low one")
    assert "[refuted] c1" in text


def test_render_markdown_escapes_pipes(tmp_path: Path) -> None:
    markdown = render_markdown(_receipt(tmp_path))
    assert "❌ Tribunal: FAIL" in markdown
    assert "fixes \\| it" in markdown
    assert "`high` b: high one" in markdown
