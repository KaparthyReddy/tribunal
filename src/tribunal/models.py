import uuid
from datetime import UTC, datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field

RECEIPT_VERSION = 2


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def utcnow() -> datetime:
    return datetime.now(UTC)


class Verdict(StrEnum):
    PASS = "pass"
    FAIL = "fail"
    INCONCLUSIVE = "inconclusive"


class Severity(StrEnum):
    INFO = "info"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class ClaimKind(StrEnum):
    FIXES = "fixes"
    NO_BEHAVIOR_CHANGE = "no_behavior_change"
    ADDS_TESTS = "adds_tests"
    PERFORMANCE = "performance"
    OTHER = "other"


class ClaimStatus(StrEnum):
    SUPPORTED = "supported"
    REFUTED = "refuted"
    UNVERIFIABLE = "unverifiable"


class SubmissionStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETE = "complete"
    ERROR = "error"


class Submission(BaseModel):
    id: str = Field(default_factory=lambda: new_id("sub"))
    repo: str
    repo_path: str
    base_sha: str
    head_sha: str
    title: str = ""
    description: str = ""
    agent: str = "unknown"
    test_command: list[str] = Field(default_factory=list)
    status: SubmissionStatus = SubmissionStatus.QUEUED
    created_at: datetime = Field(default_factory=utcnow)


class CommandRecord(BaseModel):
    argv: list[str]
    image: str
    exit_code: int | None
    timed_out: bool = False
    stdout: str = ""
    stderr: str = ""
    stdout_truncated: bool = False
    stderr_truncated: bool = False
    duration_s: float
    started_at: datetime
    side: Literal["base", "head"] | None = None
    overlay: dict[str, str] = Field(default_factory=dict)
    timeout_s: int | None = None


class Claim(BaseModel):
    id: str
    text: str
    kind: ClaimKind = ClaimKind.OTHER


class ClaimResult(BaseModel):
    claim_id: str
    status: ClaimStatus
    explanation: str = ""
    command_indexes: list[int] = Field(default_factory=list)


class Finding(BaseModel):
    source: str
    title: str
    detail: str = ""
    severity: Severity = Severity.MEDIUM
    command_indexes: list[int] = Field(default_factory=list)


class ReceiptBody(BaseModel):
    version: int = RECEIPT_VERSION
    receipt_id: str = Field(default_factory=lambda: new_id("rcp"))
    submission_id: str
    repo: str
    base_sha: str
    head_sha: str
    verdict: Verdict
    rationale: str
    claims: list[Claim] = Field(default_factory=list)
    claim_results: list[ClaimResult] = Field(default_factory=list)
    findings: list[Finding] = Field(default_factory=list)
    commands: list[CommandRecord] = Field(default_factory=list)
    blobs: dict[str, str] = Field(default_factory=dict)
    issued_at: datetime = Field(default_factory=utcnow)


class SignedReceipt(BaseModel):
    body: ReceiptBody
    digest: str
    signature: str
    public_key: str
