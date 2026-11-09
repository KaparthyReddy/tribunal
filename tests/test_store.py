from pathlib import Path

from tribunal.models import ReceiptBody, Submission, SubmissionStatus, Verdict
from tribunal.receipts import ReceiptSigner
from tribunal.store import Store


def _submission(agent: str = "codex", repo: str = "o/r") -> Submission:
    return Submission(
        repo=repo,
        repo_path="/tmp/repo",
        base_sha="a" * 40,
        head_sha="b" * 40,
        title="t",
        agent=agent,
    )


def _receipt(signer: ReceiptSigner, submission: Submission, verdict: Verdict):
    return signer.sign(
        ReceiptBody(
            submission_id=submission.id,
            repo=submission.repo,
            base_sha=submission.base_sha,
            head_sha=submission.head_sha,
            verdict=verdict,
            rationale="r",
        )
    )


def test_submission_roundtrip_and_status(tmp_path: Path) -> None:
    store = Store(tmp_path / "t.sqlite3")
    submission = _submission()
    store.add_submission(submission)

    loaded = store.get_submission(submission.id)
    assert loaded is not None
    assert loaded.status is SubmissionStatus.QUEUED

    store.set_status(submission.id, SubmissionStatus.COMPLETE)
    updated = store.get_submission(submission.id)
    assert updated is not None
    assert updated.status is SubmissionStatus.COMPLETE
    assert store.get_submission("missing") is None


def test_receipt_roundtrip_and_latest(tmp_path: Path) -> None:
    store = Store(tmp_path / "t.sqlite3")
    signer = ReceiptSigner.load_or_create(tmp_path / "k.pem")
    submission = _submission()
    store.add_submission(submission)

    first = _receipt(signer, submission, Verdict.FAIL)
    second = _receipt(signer, submission, Verdict.PASS)
    store.save_receipt(first)
    store.save_receipt(second)

    assert store.get_receipt(first.body.receipt_id) == first
    latest = store.latest_receipt_for(submission.id)
    assert latest is not None
    assert latest.body.receipt_id == second.body.receipt_id


def test_agent_verdict_counts(tmp_path: Path) -> None:
    store = Store(tmp_path / "t.sqlite3")
    signer = ReceiptSigner.load_or_create(tmp_path / "k.pem")
    for verdict in (Verdict.PASS, Verdict.PASS, Verdict.FAIL):
        submission = _submission(agent="codex")
        store.add_submission(submission)
        store.save_receipt(_receipt(signer, submission, verdict))
    other = _submission(agent="cursor")
    store.add_submission(other)
    store.save_receipt(_receipt(signer, other, Verdict.PASS))

    assert store.agent_verdict_counts("codex") == {"pass": 2, "fail": 1}
    assert store.agent_verdict_counts("codex", repo="nope/nope") == {}
    assert len(store.list_submissions()) == 4
