from pathlib import Path

import pytest

from tribunal.sandbox import WorkspaceError, materialize, resolve_sha, workspace


def test_materialize_exact_sha(make_repo, tmp_path: Path) -> None:
    repo, shas = make_repo([{"a.txt": "one\n"}, {"a.txt": "two\n", "b.txt": "new\n"}])
    dest = tmp_path / "out"
    materialize(repo, shas[0], dest)
    assert (dest / "a.txt").read_text() == "one\n"
    assert not (dest / "b.txt").exists()
    assert not (dest / ".git").exists()


def test_materialize_head(make_repo, tmp_path: Path) -> None:
    repo, shas = make_repo([{"a.txt": "one\n"}, {"a.txt": "two\n"}])
    dest = tmp_path / "out"
    materialize(repo, shas[1], dest)
    assert (dest / "a.txt").read_text() == "two\n"


def test_resolve_sha(make_repo) -> None:
    repo, shas = make_repo([{"a.txt": "one\n"}])
    assert resolve_sha(repo, "HEAD") == shas[0]
    with pytest.raises(WorkspaceError):
        resolve_sha(repo, "does-not-exist")


def test_bad_sha_raises(make_repo, tmp_path: Path) -> None:
    repo, _ = make_repo([{"a.txt": "one\n"}])
    with pytest.raises(WorkspaceError):
        materialize(repo, "f" * 40, tmp_path / "out")


def test_workspace_cleans_up(make_repo) -> None:
    repo, shas = make_repo([{"a.txt": "one\n"}])
    with workspace(repo, shas[0]) as root:
        assert (root / "a.txt").exists()
        saved = root
    assert not saved.exists()
