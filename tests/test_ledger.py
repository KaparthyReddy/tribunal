from pathlib import Path

import pytest

from tribunal.agents import JudgePolicy
from tribunal.ledger import AgentTrust, compute_trust, policy_for
from tribunal.models import ReceiptBody, Severity, Submission, Verdict
from tribunal.receipts import ReceiptSigner
from tribunal.store import Store


def _seed(store: Store, signer: ReceiptSigner, agent: str, verdicts: list[Verdict]) -> None:
    for verdict in verdicts:
        submission = Submission(
            repo="o/r",
            repo_path=".",
            base_sha="a" * 40,
            head_sha="b" * 40,
            agent=agent,
        )
        store.add_submission(submission)
        store.save_receipt(
            signer.sign(
                ReceiptBody(
                    submission_id=submission.id,
                    repo="o/r",
                    base_sha=submission.base_sha,
                    head_sha=submission.head_sha,
                    verdict=verdict,
                    rationale="r",
                )
            )
        )


@pytest.fixture
def env(tmp_path: Path) -> tuple[Store, ReceiptSigner]:
    return Store(tmp_path / "t.sqlite3"), ReceiptSigner.load_or_create(tmp_path / "k.pem")


def test_new_agent_is_standard(env) -> None:
    store, _ = env
    trust = compute_trust(store, "nobody")
    assert trust.total == 0
    assert trust.scrutiny == "standard"
    assert trust.score == 0.5


def test_short_bad_history_stays_standard(env) -> None:
    store, signer = env
    _seed(store, signer, "a", [Verdict.FAIL] * 4)
    assert compute_trust(store, "a").scrutiny == "standard"


def test_good_history_is_standard(env) -> None:
    store, signer = env
    _seed(store, signer, "a", [Verdict.PASS] * 5)
    trust = compute_trust(store, "a")
    assert trust.scrutiny == "standard"
    assert trust.passes == 5


def test_mixed_history_is_elevated(env) -> None:
    store, signer = env
    _seed(store, signer, "a", [Verdict.PASS] * 3 + [Verdict.FAIL] * 2)
    assert compute_trust(store, "a").scrutiny == "elevated"


def test_bad_history_is_high(env) -> None:
    store, signer = env
    _seed(store, signer, "a", [Verdict.FAIL] * 5)
    trust = compute_trust(store, "a")
    assert trust.scrutiny == "high"
    assert trust.fails == 5


def test_inconclusive_counts_against_score(env) -> None:
    store, signer = env
    _seed(store, signer, "a", [Verdict.INCONCLUSIVE] * 5)
    assert compute_trust(store, "a").scrutiny == "high"


def test_repo_filter(env) -> None:
    store, signer = env
    _seed(store, signer, "a", [Verdict.FAIL] * 5)
    assert compute_trust(store, "a", repo="other/repo").total == 0


@pytest.mark.parametrize(
    ("scrutiny", "expected"),
    [
        ("standard", JudgePolicy()),
        ("elevated", JudgePolicy(fail_at=Severity.HIGH, review_at=Severity.LOW)),
        ("high", JudgePolicy(fail_at=Severity.MEDIUM, review_at=Severity.LOW)),
    ],
)
def test_policy_for(scrutiny: str, expected: JudgePolicy) -> None:
    trust = AgentTrust(
        agent="a",
        passes=0,
        fails=0,
        inconclusive=0,
        total=0,
        score=0.5,
        scrutiny=scrutiny,
    )
    assert policy_for(trust) == expected
