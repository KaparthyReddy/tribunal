import json
import os
import subprocess
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

import pytest

from tribunal.models import CommandRecord
from tribunal.pipeline import Pipeline
from tribunal.receipts import ReceiptSigner
from tribunal.store import Store

GIT_ENV = {
    "GIT_AUTHOR_NAME": "t",
    "GIT_AUTHOR_EMAIL": "t@example.com",
    "GIT_COMMITTER_NAME": "t",
    "GIT_COMMITTER_EMAIL": "t@example.com",
}

BASE_LIB = "def f(a):\n    return a + 1\n"
HEAD_LIB = "def f(a):\n    return a + 2 - 1\n"
TEST_LIB = "from lib import f\n\n\ndef test_f():\n    assert f(1) == 2\n"
PROBE_CODE = (
    "import unittest\n\n\nclass T(unittest.TestCase):\n"
    "    def test_x(self):\n        self.assertTrue(True)\n"
)


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


@pytest.fixture
def scenario(make_repo) -> tuple[Path, list[str]]:
    return make_repo(
        [
            {"lib.py": BASE_LIB, "tests/test_lib.py": TEST_LIB},
            {"lib.py": HEAD_LIB},
        ]
    )


@pytest.fixture
def probes_json() -> str:
    return json.dumps({"probes": [{"name": "always passes", "code": PROBE_CODE}]})


@pytest.fixture
def is_head() -> Callable[[Path], bool]:
    def _is_head(workdir: Path) -> bool:
        return "a + 2 - 1" in (workdir / "lib.py").read_text()

    return _is_head


@pytest.fixture
def make_pipeline(tmp_path: Path) -> Callable[..., Pipeline]:
    def _make(runner, llm, **kwargs) -> Pipeline:
        store = Store(tmp_path / "tribunal.sqlite3")
        signer = ReceiptSigner.load_or_create(tmp_path / "key.pem")
        return Pipeline(store, signer, runner, llm, **kwargs)

    return _make
