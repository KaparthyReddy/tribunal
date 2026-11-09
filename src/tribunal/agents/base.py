from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from tribunal.models import ClaimResult, CommandRecord, Finding

INFRA_EXIT_CODES = frozenset({125, 126, 127})


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

    def add(self, record: CommandRecord) -> int:
        self.commands.append(record)
        return len(self.commands) - 1

    def run(
        self,
        runner: CommandRunner,
        workdir: Path,
        argv: list[str],
        *,
        env: dict[str, str] | None = None,
        timeout_s: int | None = None,
    ) -> tuple[int, CommandRecord]:
        record = runner.run(workdir, argv, env=env, timeout_s=timeout_s)
        return self.add(record), record


@dataclass
class AgentResult:
    findings: list[Finding] = field(default_factory=list)
    claim_results: list[ClaimResult] = field(default_factory=list)


def passed(record: CommandRecord) -> bool:
    return record.exit_code == 0 and not record.timed_out


def is_infra_failure(record: CommandRecord) -> bool:
    return not record.timed_out and record.exit_code in INFRA_EXIT_CODES
