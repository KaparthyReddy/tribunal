from pathlib import Path

import pytest

from conftest import git
from tribunal.gitutil import GitError, merge_base


def test_merge_base_linear(make_repo) -> None:
    repo, shas = make_repo([{"a.txt": "1\n"}, {"a.txt": "2\n"}])
    assert merge_base(repo, shas[0], shas[1]) == shas[0]


def test_merge_base_diverged(make_repo) -> None:
    repo, shas = make_repo([{"a.txt": "1\n"}])
    git(repo, "checkout", "-q", "-b", "feature")
    (repo / "f.txt").write_text("f\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "feature")
    feature = git(repo, "rev-parse", "HEAD").strip()

    git(repo, "checkout", "-q", "-")
    (repo / "m.txt").write_text("m\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "mainline")
    mainline = git(repo, "rev-parse", "HEAD").strip()

    assert merge_base(repo, mainline, feature) == shas[0]


def test_merge_base_unknown_sha(make_repo, tmp_path: Path) -> None:
    repo, shas = make_repo([{"a.txt": "1\n"}])
    with pytest.raises(GitError):
        merge_base(repo, shas[0], "f" * 40)
