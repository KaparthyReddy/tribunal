import logging
from collections.abc import Callable, Sequence
from pathlib import Path

from tribunal import gitutil
from tribunal.agents import (
    AuditContext,
    Auditor,
    BlastRadius,
    CommandRunner,
    Evidence,
    Judge,
    Skeptic,
    extract_claims,
)
from tribunal.config import Settings, get_settings
from tribunal.graph import changed_ranges
from tribunal.ledger import compute_trust, policy_for
from tribunal.llm import AnthropicClient, LLMClient, LLMError
from tribunal.models import Claim, Finding, Severity, SignedReceipt, Submission, SubmissionStatus
from tribunal.receipts import ReceiptSigner
from tribunal.sandbox import SandboxPolicy, SandboxRunner, WorkspaceError, resolve_sha, workspace
from tribunal.store import Store

log = logging.getLogger(__name__)


class SubmissionError(ValueError):
    pass


class PipelineError(RuntimeError):
    pass


class Pipeline:
    def __init__(
        self,
        store: Store,
        signer: ReceiptSigner,
        runner: CommandRunner,
        llm: LLMClient,
        *,
        allowed_roots: Sequence[Path] = (),
        prepare: Callable[[], None] | None = None,
        use_ledger: bool = True,
        blast: BlastRadius | None = None,
    ) -> None:
        self.store = store
        self.signer = signer
        self.runner = runner
        self.llm = llm
        self.allowed_roots = tuple(Path(root).expanduser().resolve() for root in allowed_roots)
        self.prepare = prepare
        self.use_ledger = use_ledger
        self.blast = blast or BlastRadius()

    def submit(
        self,
        *,
        repo_path: str | Path,
        base: str,
        head: str,
        repo: str | None = None,
        title: str = "",
        description: str = "",
        agent: str = "unknown",
        test_command: Sequence[str] | None = None,
    ) -> Submission:
        path = Path(repo_path).expanduser().resolve()
        if not path.is_dir():
            raise SubmissionError(f"{path} is not a directory")
        if self.allowed_roots and not any(path.is_relative_to(root) for root in self.allowed_roots):
            raise SubmissionError(f"{path} is outside the allowed repository roots")
        try:
            base_sha = resolve_sha(path, base)
            head_sha = resolve_sha(path, head)
        except WorkspaceError as exc:
            raise SubmissionError(str(exc)) from exc

        submission = Submission(
            repo=repo or path.name,
            repo_path=str(path),
            base_sha=base_sha,
            head_sha=head_sha,
            title=title,
            description=description,
            agent=agent,
            test_command=list(test_command or []),
        )
        self.store.add_submission(submission)
        return submission

    def run(self, submission_id: str) -> SignedReceipt:
        submission = self.store.get_submission(submission_id)
        if submission is None:
            raise PipelineError(f"unknown submission {submission_id}")
        if submission.status not in (SubmissionStatus.QUEUED, SubmissionStatus.ERROR):
            raise PipelineError(f"submission {submission_id} is {submission.status.value}")

        if self.prepare is not None:
            self.prepare()

        self.store.set_status(submission_id, SubmissionStatus.RUNNING)
        try:
            receipt = self._execute(submission)
            self.store.save_receipt(receipt)
        except Exception:
            self.store.set_status(submission_id, SubmissionStatus.ERROR)
            raise
        self.store.set_status(submission_id, SubmissionStatus.COMPLETE)
        return receipt

    def _execute(self, submission: Submission) -> SignedReceipt:
        repo = Path(submission.repo_path)
        diff = gitutil.diff(repo, submission.base_sha, submission.head_sha)
        files = gitutil.tracked_files(repo, submission.head_sha)
        ranges = changed_ranges(repo, submission.base_sha, submission.head_sha)

        findings: list[Finding] = []
        policy = None
        if self.use_ledger:
            trust = compute_trust(self.store, submission.agent, submission.repo)
            policy = policy_for(trust)
            if trust.total:
                findings.append(
                    Finding(
                        source="ledger",
                        title=(
                            f"Scrutiny {trust.scrutiny}: agent '{trust.agent}' has "
                            f"{trust.passes}/{trust.total} passing verdicts"
                        ),
                        severity=Severity.INFO,
                    )
                )

        claims: list[Claim] = []
        with (
            workspace(repo, submission.base_sha) as base_dir,
            workspace(repo, submission.head_sha) as head_dir,
        ):
            evidence = Evidence()
            ctx = AuditContext(
                submission=submission,
                base_dir=base_dir,
                head_dir=head_dir,
                evidence=evidence,
                diff=diff,
                files=files,
            )

            try:
                claims = extract_claims(self.llm, submission)
            except LLMError as exc:
                findings.append(
                    Finding(
                        source="auditor",
                        title="Claim extraction failed",
                        detail=str(exc)[:500],
                        severity=Severity.MEDIUM,
                    )
                )

            findings.extend(self.blast.analyze(head_dir, ranges).findings)
            audit = Auditor(self.llm, self.runner).audit(ctx, claims)
            findings.extend(audit.findings)
            findings.extend(Skeptic(self.llm, self.runner).attack(ctx, ranges).findings)

        return Judge(self.signer, policy).issue(
            submission, claims, audit.claim_results, findings, evidence.commands
        )


class _DeferredLLM:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._client: AnthropicClient | None = None

    def complete(self, system: str, user: str, *, max_tokens: int | None = None) -> str:
        if self._client is None:
            self._client = AnthropicClient.from_settings(self._settings)
        return self._client.complete(system, user, max_tokens=max_tokens)


def build_pipeline(
    settings: Settings | None = None,
    *,
    llm: LLMClient | None = None,
    runner: CommandRunner | None = None,
) -> Pipeline:
    settings = settings or get_settings()
    settings.ensure_dirs()
    store = Store(settings.db_path)
    signer = ReceiptSigner.load_or_create(settings.key_path)

    sandbox: SandboxRunner | None = None
    if runner is None:
        sandbox = SandboxRunner(SandboxPolicy.from_settings(settings))
        runner = sandbox

    def prepare() -> None:
        if sandbox is not None:
            sandbox.ensure_image()
        if llm is None and not settings.anthropic_api_key:
            raise LLMError("ANTHROPIC_API_KEY is not set")

    return Pipeline(
        store,
        signer,
        runner,
        llm or _DeferredLLM(settings),
        allowed_roots=settings.allowed_repo_roots,
        prepare=prepare,
        use_ledger=settings.ledger_enabled,
    )
