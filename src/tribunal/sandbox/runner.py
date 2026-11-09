import os
import shutil
import subprocess
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path

from tribunal.models import CommandRecord
from tribunal.sandbox.policy import SandboxPolicy


class SandboxUnavailableError(RuntimeError):
    pass


def docker_available() -> bool:
    if shutil.which("docker") is None:
        return False
    try:
        result = subprocess.run(["docker", "info"], capture_output=True, timeout=15)
    except (subprocess.TimeoutExpired, OSError):
        return False
    return result.returncode == 0


def _clip(data: bytes, limit: int) -> tuple[str, bool]:
    if len(data) <= limit:
        return data.decode("utf-8", "replace"), False
    half = limit // 2
    head = data[:half].decode("utf-8", "replace")
    tail = data[-half:].decode("utf-8", "replace")
    dropped = len(data) - 2 * half
    return f"{head}\n...[truncated {dropped} bytes]...\n{tail}", True


class SandboxRunner:
    def __init__(self, policy: SandboxPolicy) -> None:
        policy.validate()
        self.policy = policy

    def ensure_image(self) -> None:
        inspect = subprocess.run(
            ["docker", "image", "inspect", self.policy.image], capture_output=True
        )
        if inspect.returncode == 0:
            return
        pull = subprocess.run(["docker", "pull", self.policy.image], capture_output=True)
        if pull.returncode != 0:
            message = pull.stderr.decode("utf-8", "replace").strip()
            raise SandboxUnavailableError(f"cannot pull {self.policy.image}: {message}")

    def _user_flag(self) -> list[str]:
        if hasattr(os, "getuid"):
            return ["--user", f"{os.getuid()}:{os.getgid()}"]
        return []

    def _docker_command(
        self, name: str, workdir: Path, argv: list[str], env: dict[str, str] | None
    ) -> list[str]:
        p = self.policy
        cmd = [
            "docker",
            "run",
            "--rm",
            "--name",
            name,
            "--network",
            "none",
            "--memory",
            p.memory,
            "--memory-swap",
            p.memory,
            "--cpus",
            str(p.cpus),
            "--pids-limit",
            str(p.pids_limit),
            "--read-only",
            "--tmpfs",
            f"/tmp:rw,exec,nosuid,size={p.tmpfs_size}",
            "--cap-drop",
            "ALL",
            "--security-opt",
            "no-new-privileges",
            *self._user_flag(),
            "--mount",
            f"type=bind,source={workdir.resolve()},target=/work",
            "--workdir",
            "/work",
            "--env",
            "HOME=/tmp",
            "--env",
            "PYTHONDONTWRITEBYTECODE=1",
            "--env",
            "PYTHONHASHSEED=0",
        ]
        for key, value in (env or {}).items():
            cmd += ["--env", f"{key}={value}"]
        cmd += [p.image, *argv]
        return cmd

    def run(
        self,
        workdir: Path,
        argv: list[str],
        *,
        env: dict[str, str] | None = None,
        timeout_s: int | None = None,
    ) -> CommandRecord:
        if not argv:
            raise ValueError("argv must not be empty")

        name = f"tribunal-{uuid.uuid4().hex[:12]}"
        timeout = timeout_s or self.policy.timeout_s
        cmd = self._docker_command(name, workdir, argv, env)

        started_at = datetime.now(UTC)
        t0 = time.monotonic()
        timed_out = False
        exit_code: int | None

        try:
            proc = subprocess.run(cmd, capture_output=True, timeout=timeout)
            exit_code = proc.returncode
            out, err = proc.stdout, proc.stderr
        except subprocess.TimeoutExpired as exc:
            timed_out = True
            subprocess.run(["docker", "kill", name], capture_output=True)
            exit_code = None
            out = exc.stdout or b""
            err = exc.stderr or b""
        except FileNotFoundError as exc:
            raise SandboxUnavailableError("docker executable not found") from exc

        duration = time.monotonic() - t0
        limit = self.policy.max_output_bytes
        stdout, stdout_truncated = _clip(out, limit)
        stderr, stderr_truncated = _clip(err, limit)

        return CommandRecord(
            argv=argv,
            image=self.policy.image,
            exit_code=exit_code,
            timed_out=timed_out,
            stdout=stdout,
            stderr=stderr,
            stdout_truncated=stdout_truncated,
            stderr_truncated=stderr_truncated,
            duration_s=round(duration, 3),
            started_at=started_at,
        )
