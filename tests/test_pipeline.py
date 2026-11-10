from pathlib import Path

import pytest

from tribunal.llm import ScriptedLLM
from tribunal.models import ReceiptBody, Severity, Submission, SubmissionStatus, Verdict
from tribunal.pipeline import PipelineError, SubmissionError
from tribunal.receipts import verify_receipt


def test_pass_end_to_end(scenario, make_runner, make_pipeline, probes_json) -> None:
    repo, shas = scenario
    runner = make_runner(lambda workdir, argv: (0, "ok", ""))
    pipe = make_pipeline(runner, ScriptedLLM([probes_json]))

    submission = pipe.submit(repo_path=str(repo), base=shas[0], head=shas[1], agent="codex")
    assert submission.base_sha == shas[0]
    assert submission.head_sha == shas[1]
    assert submission.repo == "repo"

    receipt = pipe.run(submission.id)
    assert receipt.body.verdict is Verdict.PASS
    assert receipt.body.head_sha == shas[1]
    assert len(receipt.body.commands) == 1
    assert verify_receipt(receipt)

    stored = pipe.store.get_submission(submission.id)
    assert stored is not None
    assert stored.status is SubmissionStatus.COMPLETE
    assert pipe.store.latest_receipt_for(submission.id) == receipt


def test_regression_fails(scenario, make_runner, make_pipeline, probes_json, is_head) -> None:
    repo, shas = scenario
    runner = make_runner(
        lambda workdir, argv: (1, "FAILED", "") if is_head(workdir) else (0, "", "")
    )
    pipe = make_pipeline(runner, ScriptedLLM([probes_json]))

    submission = pipe.submit(
        repo_path=str(repo),
        base=shas[0],
        head=shas[1],
        test_command=["pytest"],
    )
    receipt = pipe.run(submission.id)

    assert receipt.body.verdict is Verdict.FAIL
    titles = [f.title for f in receipt.body.findings]
    assert any("Regression" in title for title in titles)
    assert any("Probe broke the change" in title for title in titles)
    assert receipt.body.findings[0].severity is Severity.HIGH


def test_runner_exception_sets_error_status(
    scenario, make_runner, make_pipeline, probes_json
) -> None:
    repo, shas = scenario

    def boom(workdir: Path, argv: list[str]) -> tuple[int, str, str]:
        raise RuntimeError("boom")

    pipe = make_pipeline(make_runner(boom), ScriptedLLM([probes_json]))
    submission = pipe.submit(repo_path=str(repo), base=shas[0], head=shas[1])

    with pytest.raises(RuntimeError):
        pipe.run(submission.id)
    stored = pipe.store.get_submission(submission.id)
    assert stored is not None
    assert stored.status is SubmissionStatus.ERROR
    assert pipe.store.latest_receipt_for(submission.id) is None


def test_completed_submission_cannot_rerun(
    scenario, make_runner, make_pipeline, probes_json
) -> None:
    repo, shas = scenario
    runner = make_runner(lambda workdir, argv: (0, "ok", ""))
    pipe = make_pipeline(runner, ScriptedLLM([probes_json]))
    submission = pipe.submit(repo_path=str(repo), base=shas[0], head=shas[1])
    pipe.run(submission.id)

    with pytest.raises(PipelineError):
        pipe.run(submission.id)
    with pytest.raises(PipelineError):
        pipe.run("sub_missing")


def test_prepare_runs_before_execution(scenario, make_runner, make_pipeline, probes_json) -> None:
    repo, shas = scenario
    calls: list[int] = []
    runner = make_runner(lambda workdir, argv: (0, "ok", ""))
    pipe = make_pipeline(runner, ScriptedLLM([probes_json]), prepare=lambda: calls.append(1))
    submission = pipe.submit(repo_path=str(repo), base=shas[0], head=shas[1])
    pipe.run(submission.id)
    assert calls == [1]


def test_prepare_failure_leaves_submission_queued(scenario, make_runner, make_pipeline) -> None:
    repo, shas = scenario

    def failing() -> None:
        raise RuntimeError("no docker")

    runner = make_runner(lambda workdir, argv: (0, "", ""))
    pipe = make_pipeline(runner, ScriptedLLM([]), prepare=failing)
    submission = pipe.submit(repo_path=str(repo), base=shas[0], head=shas[1])

    with pytest.raises(RuntimeError):
        pipe.run(submission.id)
    stored = pipe.store.get_submission(submission.id)
    assert stored is not None
    assert stored.status is SubmissionStatus.QUEUED


def test_submit_validation(scenario, make_runner, make_pipeline, tmp_path: Path) -> None:
    repo, shas = scenario
    runner = make_runner(lambda workdir, argv: (0, "", ""))
    pipe = make_pipeline(runner, ScriptedLLM([]))

    with pytest.raises(SubmissionError):
        pipe.submit(repo_path=str(repo), base="nope", head=shas[1])
    with pytest.raises(SubmissionError):
        pipe.submit(repo_path=str(tmp_path / "missing"), base="a", head="b")
    with pytest.raises(SubmissionError):
        pipe.submit(repo_path=str(tmp_path), base="HEAD", head="HEAD")


def test_allowed_roots_enforced(scenario, make_runner, make_pipeline, tmp_path: Path) -> None:
    repo, shas = scenario
    runner = make_runner(lambda workdir, argv: (0, "", ""))

    restricted = make_pipeline(runner, ScriptedLLM([]), allowed_roots=[tmp_path / "elsewhere"])
    with pytest.raises(SubmissionError):
        restricted.submit(repo_path=str(repo), base=shas[0], head=shas[1])

    allowed = make_pipeline(runner, ScriptedLLM([]), allowed_roots=[tmp_path])
    submission = allowed.submit(repo_path=str(repo), base=shas[0], head=shas[1])
    assert submission.head_sha == shas[1]


def test_ledger_finding_added_for_known_agent(
    scenario, make_runner, make_pipeline, probes_json
) -> None:
    repo, shas = scenario
    runner = make_runner(lambda workdir, argv: (0, "ok", ""))
    pipe = make_pipeline(runner, ScriptedLLM([probes_json]))

    for _ in range(5):
        old = Submission(
            repo="repo",
            repo_path=str(repo),
            base_sha=shas[0],
            head_sha=shas[1],
            agent="sloppy",
        )
        pipe.store.add_submission(old)
        pipe.store.save_receipt(
            pipe.signer.sign(
                ReceiptBody(
                    submission_id=old.id,
                    repo="repo",
                    base_sha=old.base_sha,
                    head_sha=old.head_sha,
                    verdict=Verdict.FAIL,
                    rationale="r",
                )
            )
        )

    submission = pipe.submit(repo_path=str(repo), base=shas[0], head=shas[1], agent="sloppy")
    receipt = pipe.run(submission.id)
    ledger = [f for f in receipt.body.findings if f.source == "ledger"]
    assert len(ledger) == 1
    assert "Scrutiny high" in ledger[0].title
    assert receipt.body.verdict is Verdict.PASS


def test_ledger_can_be_disabled(scenario, make_runner, make_pipeline, probes_json) -> None:
    repo, shas = scenario
    runner = make_runner(lambda workdir, argv: (0, "ok", ""))
    pipe = make_pipeline(runner, ScriptedLLM([probes_json]), use_ledger=False)
    submission = pipe.submit(repo_path=str(repo), base=shas[0], head=shas[1])
    receipt = pipe.run(submission.id)
    assert not [f for f in receipt.body.findings if f.source == "ledger"]
