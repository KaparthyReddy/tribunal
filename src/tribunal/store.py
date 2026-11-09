import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from tribunal.models import SignedReceipt, Submission, SubmissionStatus

SCHEMA = """
CREATE TABLE IF NOT EXISTS submissions (
    id TEXT PRIMARY KEY,
    repo TEXT NOT NULL,
    head_sha TEXT NOT NULL,
    agent TEXT NOT NULL,
    status TEXT NOT NULL,
    payload TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS receipts (
    id TEXT PRIMARY KEY,
    submission_id TEXT NOT NULL REFERENCES submissions(id),
    verdict TEXT NOT NULL,
    digest TEXT NOT NULL,
    payload TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_submissions_repo_agent ON submissions(repo, agent);
CREATE INDEX IF NOT EXISTS idx_receipts_submission ON receipts(submission_id);
"""


class Store:
    def __init__(self, path: Path) -> None:
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.executescript(SCHEMA)

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.path, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def add_submission(self, submission: Submission) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO submissions (id, repo, head_sha, agent, status, payload, created_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    submission.id,
                    submission.repo,
                    submission.head_sha,
                    submission.agent,
                    submission.status.value,
                    submission.model_dump_json(),
                    submission.created_at.isoformat(),
                ),
            )

    def get_submission(self, submission_id: str) -> Submission | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT payload, status FROM submissions WHERE id = ?", (submission_id,)
            ).fetchone()
        if row is None:
            return None
        submission = Submission.model_validate_json(row["payload"])
        return submission.model_copy(update={"status": SubmissionStatus(row["status"])})

    def set_status(self, submission_id: str, status: SubmissionStatus) -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE submissions SET status = ? WHERE id = ?",
                (status.value, submission_id),
            )

    def list_submissions(self, limit: int = 50, repo: str | None = None) -> list[Submission]:
        query = "SELECT payload, status FROM submissions"
        params: list[object] = []
        if repo is not None:
            query += " WHERE repo = ?"
            params.append(repo)
        query += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)
        with self._connect() as conn:
            rows = conn.execute(query, params).fetchall()
        return [
            Submission.model_validate_json(row["payload"]).model_copy(
                update={"status": SubmissionStatus(row["status"])}
            )
            for row in rows
        ]

    def save_receipt(self, receipt: SignedReceipt) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO receipts (id, submission_id, verdict, digest, payload, created_at)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                (
                    receipt.body.receipt_id,
                    receipt.body.submission_id,
                    receipt.body.verdict.value,
                    receipt.digest,
                    receipt.model_dump_json(),
                    receipt.body.issued_at.isoformat(),
                ),
            )

    def get_receipt(self, receipt_id: str) -> SignedReceipt | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT payload FROM receipts WHERE id = ?", (receipt_id,)
            ).fetchone()
        return SignedReceipt.model_validate_json(row["payload"]) if row else None

    def latest_receipt_for(self, submission_id: str) -> SignedReceipt | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT payload FROM receipts WHERE submission_id = ?"
                " ORDER BY created_at DESC LIMIT 1",
                (submission_id,),
            ).fetchone()
        return SignedReceipt.model_validate_json(row["payload"]) if row else None

    def agent_verdict_counts(self, agent: str, repo: str | None = None) -> dict[str, int]:
        query = (
            "SELECT r.verdict AS verdict, COUNT(*) AS n FROM receipts r"
            " JOIN submissions s ON s.id = r.submission_id WHERE s.agent = ?"
        )
        params: list[object] = [agent]
        if repo is not None:
            query += " AND s.repo = ?"
            params.append(repo)
        query += " GROUP BY r.verdict"
        with self._connect() as conn:
            rows = conn.execute(query, params).fetchall()
        return {row["verdict"]: row["n"] for row in rows}
