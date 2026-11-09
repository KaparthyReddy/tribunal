import subprocess
from pathlib import Path


class GitError(RuntimeError):
    pass


def _git(repo_path: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo_path), *args],
        capture_output=True,
    )
    if result.returncode != 0:
        message = result.stderr.decode("utf-8", "replace").strip()
        raise GitError(f"git {' '.join(args)} failed: {message}")
    return result.stdout.decode("utf-8", "replace")


def diff(repo_path: Path, base_sha: str, head_sha: str, max_chars: int = 20000) -> str:
    text = _git(repo_path, "diff", "--no-color", "--no-ext-diff", f"{base_sha}..{head_sha}")
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + f"\n...[diff truncated, {len(text) - max_chars} more chars]\n"


def changed_files(repo_path: Path, base_sha: str, head_sha: str) -> list[str]:
    text = _git(repo_path, "diff", "--name-only", f"{base_sha}..{head_sha}")
    return [line for line in text.splitlines() if line]


def tracked_files(repo_path: Path, sha: str, limit: int = 300) -> list[str]:
    text = _git(repo_path, "ls-tree", "-r", "--name-only", sha)
    return text.splitlines()[:limit]
