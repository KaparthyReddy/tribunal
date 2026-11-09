import shutil
import subprocess
import tarfile
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path


class WorkspaceError(RuntimeError):
    pass


def resolve_sha(repo_path: Path, ref: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo_path), "rev-parse", "--verify", f"{ref}^{{commit}}"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise WorkspaceError(f"cannot resolve {ref!r} in {repo_path}: {result.stderr.strip()}")
    return result.stdout.strip()


def materialize(repo_path: Path, sha: str, dest: Path) -> None:
    dest.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryFile() as stderr_file:
        proc = subprocess.Popen(
            ["git", "-C", str(repo_path), "archive", "--format=tar", sha],
            stdout=subprocess.PIPE,
            stderr=stderr_file,
        )
        try:
            assert proc.stdout is not None
            with tarfile.open(fileobj=proc.stdout, mode="r|") as tar:
                tar.extractall(dest, filter="data")
        except tarfile.TarError as exc:
            proc.kill()
            raise WorkspaceError(f"failed to extract archive for {sha}: {exc}") from exc
        finally:
            if proc.stdout is not None:
                proc.stdout.close()
            returncode = proc.wait()
        if returncode != 0:
            stderr_file.seek(0)
            message = stderr_file.read().decode("utf-8", "replace").strip()
            raise WorkspaceError(f"git archive failed for {sha}: {message}")


@contextmanager
def workspace(repo_path: Path, sha: str) -> Iterator[Path]:
    root = Path(tempfile.mkdtemp(prefix="tribunal-"))
    try:
        materialize(repo_path, sha, root)
        yield root
    finally:
        shutil.rmtree(root, ignore_errors=True)
