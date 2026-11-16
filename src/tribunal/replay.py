import hashlib
import re
from collections.abc import Callable, Iterator
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass, field, replace
from pathlib import Path, PurePosixPath
from typing import Any, Literal

from tribunal.agents.base import CommandRunner
from tribunal.models import CommandRecord, SignedReceipt
from tribunal.receipts import verify_receipt
from tribunal.sandbox import SandboxRunner, WorkspaceError, workspace

RunnerFactory = Callable[[str], CommandRunner]
Status = Literal["reproduced", "output_differs", "diverged", "skipped"]
Overall = Literal["reproduced", "diverged", "incomplete", "empty"]

NOISE = re.compile(r"\b\d+(?:\.\d+)?s\b|0x[0-9a-fA-F]+")


class ReplayError(RuntimeError):
    pass


@dataclass(frozen=True)
class CommandReplay:
    index: int
    status: Status
    detail: str = ""


@dataclass
class ReplayReport:
    receipt_id: str
    results: list[CommandReplay] = field(default_factory=list)

    def count(self, status: Status) -> int:
        return sum(1 for result in self.results if result.status == status)

    @property
    def overall(self) -> Overall:
        if not self.results:
            return "empty"
        if self.count("diverged"):
            return "diverged"
        if self.count("skipped"):
            return "incomplete"
        return "reproduced"

    def as_dict(self) -> dict[str, Any]:
        return {
            "receipt_id": self.receipt_id,
            "overall": self.overall,
            "commands": len(self.results),
            "reproduced": self.count("reproduced"),
            "output_differs": self.count("output_differs"),
            "diverged": self.count("diverged"),
            "skipped": self.count("skipped"),
            "issues": [
                {"index": result.index, "status": result.status, "detail": result.detail}
                for result in self.results
                if result.status in ("diverged", "skipped")
            ],
        }


def _normalize(text: str) -> str:
    return NOISE.sub("<n>", text)


def _outcome(record: CommandRecord) -> str:
    return "timed out" if record.timed_out else f"exit {record.exit_code}"


def _safe_target(root: Path, relative: str) -> Path:
    pure = PurePosixPath(relative)
    if not relative or pure.is_absolute() or ".." in pure.parts or "\\" in relative:
        raise ReplayError(f"unsafe artifact path {relative!r}")
    resolved_root = root.resolve()
    target = (resolved_root / Path(*pure.parts)).resolve()
    if target == resolved_root or not target.is_relative_to(resolved_root):
        raise ReplayError(f"unsafe artifact path {relative!r}")
    return target


@contextmanager
def _overlaid(root: Path, files: dict[str, str]) -> Iterator[None]:
    saved: list[tuple[Path, bytes | None]] = []
    new_dirs: list[Path] = []
    try:
        for relative, content in files.items():
            target = _safe_target(root, relative)
            previous = target.read_bytes() if target.is_file() else None
            parent = target.parent
            missing: list[Path] = []
            while not parent.exists():
                missing.append(parent)
                parent = parent.parent
            target.parent.mkdir(parents=True, exist_ok=True)
            new_dirs.extend(missing)
            target.write_bytes(content.encode("utf-8"))
            saved.append((target, previous))
        yield
    finally:
        for target, previous in reversed(saved):
            if previous is None:
                target.unlink(missing_ok=True)
            else:
                target.write_bytes(previous)
        for directory in sorted(set(new_dirs), key=lambda path: len(path.parts), reverse=True):
            try:
                directory.rmdir()
            except OSError:
                pass


def _compare(index: int, original: CommandRecord, replayed: CommandRecord) -> CommandReplay:
    if replayed.timed_out != original.timed_out or replayed.exit_code != original.exit_code:
        return CommandReplay(
            index,
            "diverged",
            f"{_outcome(original)} originally, {_outcome(replayed)} on replay",
        )
    same = _normalize(replayed.stdout) == _normalize(original.stdout) and _normalize(
        replayed.stderr
    ) == _normalize(original.stderr)
    if same:
        return CommandReplay(index, "reproduced")
    return CommandReplay(index, "output_differs", "same outcome, different output")


def _replay_one(
    index: int,
    command: CommandRecord,
    blobs: dict[str, str],
    roots: dict[str, Path],
    runner_for: RunnerFactory,
) -> CommandReplay:
    if command.side is None:
        return CommandReplay(index, "skipped", "no replay data (receipt predates version 2)")

    files: dict[str, str] = {}
    for path, digest in command.overlay.items():
        content = blobs.get(digest)
        if content is None:
            return CommandReplay(index, "skipped", f"artifact {path} was not stored in the receipt")
        if hashlib.sha256(content.encode("utf-8")).hexdigest() != digest:
            return CommandReplay(index, "skipped", f"artifact {path} does not match its digest")
        files[path] = content

    root = roots[command.side]
    try:
        with _overlaid(root, files):
            replayed = runner_for(command.image).run(
                root, command.argv, timeout_s=command.timeout_s
            )
    except ReplayError as exc:
        return CommandReplay(index, "skipped", str(exc))
    return _compare(index, command, replayed)


def replay_receipt(
    receipt: SignedReceipt, repo_path: Path, runner_for: RunnerFactory
) -> ReplayReport:
    if not verify_receipt(receipt):
        raise ReplayError("receipt failed verification; refusing to replay it")

    body = receipt.body
    report = ReplayReport(receipt_id=body.receipt_id)
    if not body.commands:
        return report

    shas = {"base": body.base_sha, "head": body.head_sha}
    needed = sorted({command.side for command in body.commands if command.side is not None})

    with ExitStack() as stack:
        roots: dict[str, Path] = {}
        for side in needed:
            try:
                roots[side] = stack.enter_context(workspace(repo_path, shas[side]))
            except WorkspaceError as exc:
                raise ReplayError(f"cannot check out the {side} commit: {exc}") from exc
        for index, command in enumerate(body.commands):
            report.results.append(_replay_one(index, command, body.blobs, roots, runner_for))
    return report


def runner_factory_from(runner: CommandRunner) -> RunnerFactory:
    if not isinstance(runner, SandboxRunner):
        return lambda image: runner

    ready: dict[str, CommandRunner] = {}

    def factory(image: str) -> CommandRunner:
        if image not in ready:
            candidate = (
                runner
                if image == runner.policy.image
                else SandboxRunner(replace(runner.policy, image=image))
            )
            candidate.ensure_image()
            ready[image] = candidate
        return ready[image]

    return factory
