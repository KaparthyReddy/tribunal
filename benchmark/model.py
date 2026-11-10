import subprocess
import textwrap
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

TEST_COMMAND = ["python", "-m", "unittest"]


def code(text: str) -> str:
    return textwrap.dedent(text).lstrip("\n")


@dataclass(frozen=True)
class Case:
    id: str
    category: str
    expect: Literal["buggy", "clean"]
    title: str
    description: str
    base: dict[str, str]
    head: dict[str, str]
    tests_catch: bool = False
    note: str = ""


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        [
            "git",
            "-C",
            str(repo),
            "-c",
            "commit.gpgsign=false",
            "-c",
            "user.name=bench",
            "-c",
            "user.email=bench@example.com",
            *args,
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout


def _write(repo: Path, files: dict[str, str]) -> None:
    for relative, content in files.items():
        path = repo / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")


def build_repo(case: Case, root: Path) -> tuple[Path, str, str]:
    repo = root / case.id
    repo.mkdir(parents=True)
    _git(repo, "init", "-q")

    _write(repo, case.base)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "base")
    base_sha = _git(repo, "rev-parse", "HEAD").strip()

    _write(repo, case.head)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", case.title)
    head_sha = _git(repo, "rev-parse", "HEAD").strip()
    return repo, base_sha, head_sha
