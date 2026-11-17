import hashlib
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from tribunal.models import ClaimKind, ClaimResult, CommandRecord, Finding

INFRA_EXIT_CODES = frozenset({125, 126, 127})
MAX_BLOB_BYTES = 512_000
CRITICAL_KINDS = frozenset({ClaimKind.FIXES, ClaimKind.NO_BEHAVIOR_CHANGE})


class CommandRunner(Protocol):
    def run(
        self,
        workdir: Path,
        argv: list[str],
        *,
        env: dict[str, str] | None = None,
        timeout_s: int | None = None,
    ) -> CommandRecord: ...


@dataclass
class Evidence:
    commands: list[CommandRecord] = field(default_factory=list)
    blobs: dict[str, str] = field(default_factory=dict)
    sides: dict[Path, str] = field(default_factory=dict)
    blob_budget: int = MAX_BLOB_BYTES
    stored_bytes: int = field(default=0, init=False)

    def _blob(self, content: str) -> str:
        data = content.encode("utf-8")
        digest = hashlib.sha256(data).hexdigest()
        if digest not in self.blobs and self.stored_bytes + len(data) <= self.blob_budget:
            self.blobs[digest] = content
            self.stored_bytes += len(data)
        return digest

    def add(
        self,
        record: CommandRecord,
        *,
        workdir: Path | None = None,
        overlay: Mapping[str, str] | None = None,
        timeout_s: int | None = None,
    ) -> int:
        update: dict[str, object] = {}
        side = self.sides.get(workdir) if workdir is not None else None
        if side is not None:
            update["side"] = side
        if overlay:
            update["overlay"] = {
                path: self._blob(content) for path, content in sorted(overlay.items())
            }
        if record.timeout_s is None and timeout_s is not None:
            update["timeout_s"] = timeout_s
        self.commands.append(record.model_copy(update=update) if update else record)
        return len(self.commands) - 1

    def run(
        self,
        runner: CommandRunner,
        workdir: Path,
        argv: list[str],
        *,
        env: dict[str, str] | None = None,
        timeout_s: int | None = None,
        overlay: Mapping[str, str] | None = None,
    ) -> tuple[int, CommandRecord]:
        record = runner.run(workdir, argv, env=env, timeout_s=timeout_s)
        index = self.add(record, workdir=workdir, overlay=overlay, timeout_s=timeout_s)
        return index, self.commands[index]


@dataclass
class AgentResult:
    findings: list[Finding] = field(default_factory=list)
    claim_results: list[ClaimResult] = field(default_factory=list)
    behavior_identical: bool = False


def passed(record: CommandRecord) -> bool:
    return record.exit_code == 0 and not record.timed_out


def is_infra_failure(record: CommandRecord) -> bool:
    return not record.timed_out and record.exit_code in INFRA_EXIT_CODES
