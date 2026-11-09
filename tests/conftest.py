import os
import subprocess
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

import pytest

from tribunal.models import CommandRecord

GIT_ENV = {
    "GIT_AUTHOR_NAME": "t",
    "GIT_AUTHOR_EMAIL": "t@example.com",
    "GIT_COMMITTER_NAME": "t",
    "GIT_COMMITTER_EMAIL": "t@example.com",
}


def git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), "-c", "commit.gpgsign=false", *args],
        capture_output=True,
        text=True,
        env={**os.environ, **GIT_ENV},
        check=True,
    )
    return result.stdout


class FakeRunner:
    def __init__(self, handler: Callable[[Path, list[str]], tuple[int, str, str]]) -> None:
        self.handler = handler
        self.calls: list[tuple[Path, list[str]]] = []

    def run(
        self,
        workdir: Path,
        argv: list[str],
        *,
        env: dict[str, str] | None = None,
        timeout_s: int | None = None,
    ) -> CommandRecord:
        self.calls.append((workdir, argv))
        code, stdout, stderr = self.handler(workdir, argv)
        return CommandRecord(
            argv=argv,
            image="fake",
            exit_code=code,
            stdout=stdout,
            stderr=stderr,
            duration_s=0.01,
            started_at=datetime.now(UTC),
        )


@pytest.fixture
def make_repo(tmp_path: Path) -> Callable[[list[dict[str, str]]], tuple[Path, list[str]]]:
    def _make(commits: list[dict[str, str]]) -> tuple[Path, list[str]]:
        repo = tmp_path / "repo"
        repo.mkdir()
        git(repo, "init", "-q")
        shas: list[str] = []
        for files in commits:
            for rel, content in files.items():
                target = repo / rel
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(content)
            git(repo, "add", "-A")
            git(repo, "commit", "-q", "-m", f"commit {len(shas)}")
            shas.append(git(repo, "rev-parse", "HEAD").strip())
        return repo, shas

    return _make


@pytest.fixture
def make_runner() -> Callable[[Callable[[Path, list[str]], tuple[int, str, str]]], FakeRunner]:
    def _make(handler: Callable[[Path, list[str]], tuple[int, str, str]]) -> FakeRunner:
        return FakeRunner(handler)

    return _make
