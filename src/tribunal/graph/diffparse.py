import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

from tribunal.gitutil import GitError

HUNK = re.compile(r"^@@ -\d+(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")
HUNK_SIDES = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")


@dataclass(frozen=True)
class FileChange:
    added: tuple[tuple[int, int], ...] = ()
    removed: tuple[tuple[int, int], ...] = ()


def parse_unified_diff_ranges(text: str) -> dict[str, list[tuple[int, int]]]:
    ranges: dict[str, list[tuple[int, int]]] = {}
    current: str | None = None
    old_left = 0
    new_left = 0

    for line in text.splitlines():
        if old_left > 0 or new_left > 0:
            if line.startswith("-"):
                old_left -= 1
            elif line.startswith("+"):
                new_left -= 1
            elif line.startswith(" "):
                old_left -= 1
                new_left -= 1
            continue

        if line.startswith("+++ "):
            target = line[4:].split("\t")[0].strip()
            if target == "/dev/null":
                current = None
            else:
                current = target[2:] if target.startswith("b/") else target
                ranges.setdefault(current, [])
            continue

        match = HUNK.match(line)
        if match is None or current is None:
            continue
        old_count = int(match.group(1)) if match.group(1) is not None else 1
        start = int(match.group(2))
        new_count = int(match.group(3)) if match.group(3) is not None else 1
        old_left = old_count
        new_left = new_count
        if new_count == 0:
            position = max(start, 1)
            ranges[current].append((position, position))
        else:
            ranges[current].append((start, start + new_count - 1))

    return ranges


def parse_unified_diff_sides(text: str) -> dict[str, FileChange]:
    added: dict[str, list[tuple[int, int]]] = {}
    removed: dict[str, list[tuple[int, int]]] = {}
    current: str | None = None
    old_left = 0
    new_left = 0

    for line in text.splitlines():
        if old_left > 0 or new_left > 0:
            if line.startswith("-"):
                old_left -= 1
            elif line.startswith("+"):
                new_left -= 1
            elif line.startswith(" "):
                old_left -= 1
                new_left -= 1
            continue

        if line.startswith("+++ "):
            target = line[4:].split("\t")[0].strip()
            if target == "/dev/null":
                current = None
            else:
                current = target[2:] if target.startswith("b/") else target
                added.setdefault(current, [])
                removed.setdefault(current, [])
            continue

        match = HUNK_SIDES.match(line)
        if match is None or current is None:
            continue
        old_start = int(match.group(1))
        old_count = int(match.group(2)) if match.group(2) is not None else 1
        new_start = int(match.group(3))
        new_count = int(match.group(4)) if match.group(4) is not None else 1
        old_left = old_count
        new_left = new_count
        if old_count > 0:
            removed[current].append((old_start, old_start + old_count - 1))
        if new_count > 0:
            added[current].append((new_start, new_start + new_count - 1))

    return {file: FileChange(tuple(added[file]), tuple(removed[file])) for file in added}


def _diff_text(repo_path: Path, base_sha: str, head_sha: str) -> str:
    result = subprocess.run(
        [
            "git",
            "-C",
            str(repo_path),
            "-c",
            "core.quotepath=off",
            "diff",
            "--no-color",
            "--no-ext-diff",
            "-U0",
            f"{base_sha}..{head_sha}",
        ],
        capture_output=True,
    )
    if result.returncode != 0:
        message = result.stderr.decode("utf-8", "replace").strip()
        raise GitError(f"git diff failed: {message}")
    return result.stdout.decode("utf-8", "replace")


def changed_ranges(
    repo_path: Path, base_sha: str, head_sha: str
) -> dict[str, list[tuple[int, int]]]:
    return parse_unified_diff_ranges(_diff_text(repo_path, base_sha, head_sha))


def changed_sides(repo_path: Path, base_sha: str, head_sha: str) -> dict[str, FileChange]:
    return parse_unified_diff_sides(_diff_text(repo_path, base_sha, head_sha))
