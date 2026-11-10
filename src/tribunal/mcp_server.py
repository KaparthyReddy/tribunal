import logging
import threading
from collections.abc import Callable
from typing import Any

from mcp.server.fastmcp import FastMCP

from tribunal.config import Settings, get_settings
from tribunal.pipeline import Pipeline, SubmissionError, build_pipeline
from tribunal.receipts import verify_receipt
from tribunal.summary import summarize

log = logging.getLogger(__name__)

INSTRUCTIONS = (
    "Tribunal verifies AI-written code changes. Call submit with a local git repository, a "
    "base ref and a head ref. It runs adversarial checks in a network-less sandbox and returns "
    "a signed verdict. Treat a fail verdict as blocking and inconclusive as needing human review."
)


class TribunalTools:
    def __init__(self, factory: Callable[[], Pipeline]) -> None:
        self._factory = factory
        self._pipeline: Pipeline | None = None
        self._lock = threading.Lock()

    @property
    def pipeline(self) -> Pipeline:
        with self._lock:
            if self._pipeline is None:
                self._pipeline = self._factory()
            return self._pipeline

    def submit(
        self,
        repo_path: str,
        base: str,
        head: str = "HEAD",
        title: str = "",
        description: str = "",
        agent: str = "unknown",
        test_command: list[str] | None = None,
        repo: str | None = None,
    ) -> dict[str, Any]:
        pipeline = self.pipeline
        try:
            submission = pipeline.submit(
                repo_path=repo_path,
                base=base,
                head=head,
                repo=repo,
                title=title,
                description=description,
                agent=agent,
                test_command=test_command,
            )
        except SubmissionError as exc:
            return {"error": str(exc)}
        try:
            receipt = pipeline.run(submission.id)
        except Exception as exc:
            log.exception("verification failed for %s", submission.id)
            return {"submission_id": submission.id, "error": f"verification failed: {exc}"}
        return summarize(receipt)

    def verdict(self, submission_id: str) -> dict[str, Any]:
        store = self.pipeline.store
        submission = store.get_submission(submission_id)
        if submission is None:
            return {"error": f"unknown submission {submission_id}"}
        result: dict[str, Any] = {
            "submission_id": submission_id,
            "status": submission.status.value,
        }
        receipt = store.latest_receipt_for(submission_id)
        if receipt is not None:
            result.update(summarize(receipt))
        return result

    def verify(self, receipt_id: str) -> dict[str, Any]:
        pipeline = self.pipeline
        receipt = pipeline.store.get_receipt(receipt_id)
        if receipt is None:
            return {"error": f"unknown receipt {receipt_id}"}
        return {
            "receipt_id": receipt_id,
            "intact": verify_receipt(receipt),
            "trusted": receipt.public_key == pipeline.signer.public_key_b64,
        }


def create_server(pipeline: Pipeline | None = None, settings: Settings | None = None) -> FastMCP:
    resolved = settings or get_settings()
    tools = TribunalTools(lambda: pipeline if pipeline is not None else build_pipeline(resolved))
    server = FastMCP("tribunal", instructions=INSTRUCTIONS)

    @server.tool()
    def submit(
        repo_path: str,
        base: str,
        head: str = "HEAD",
        title: str = "",
        description: str = "",
        agent: str = "unknown",
        test_command: list[str] | None = None,
        repo: str | None = None,
    ) -> dict[str, Any]:
        """Verify a code change between two git refs of a local repository.

        Runs the Skeptic, Auditor and blast-radius checks in a sandbox and returns a signed
        verdict (pass, fail or inconclusive) with findings and a receipt id. Pass the PR title
        and description so every claim in them is checked. test_command is the argv that runs
        the project's tests, for example ["python", "-m", "pytest", "-q"].
        """
        return tools.submit(repo_path, base, head, title, description, agent, test_command, repo)

    @server.tool()
    def verdict(submission_id: str) -> dict[str, Any]:
        """Return the status and latest verdict for a previous submission."""
        return tools.verdict(submission_id)

    @server.tool()
    def verify(receipt_id: str) -> dict[str, Any]:
        """Check a receipt's digest and Ed25519 signature, and whether this server signed it."""
        return tools.verify(receipt_id)

    return server
