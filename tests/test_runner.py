from pathlib import Path

import pytest

from tribunal.sandbox import SandboxPolicy, SandboxRunner, docker_available
from tribunal.sandbox.runner import _clip

needs_docker = pytest.mark.skipif(not docker_available(), reason="docker unavailable")


def _flag_value(cmd: list[str], flag: str) -> str:
    return cmd[cmd.index(flag) + 1]


def test_clip_short_and_long() -> None:
    text, truncated = _clip(b"hello", 100)
    assert text == "hello"
    assert not truncated

    text, truncated = _clip(b"x" * 5000, 1000)
    assert truncated
    assert "truncated" in text


def test_docker_command_flags(tmp_path: Path) -> None:
    runner = SandboxRunner(SandboxPolicy(image="img:1", memory="256m", cpus=2.0))
    cmd = runner._docker_command("n1", tmp_path, ["echo", "hi"], {"A": "b"})
    assert _flag_value(cmd, "--network") == "none"
    assert _flag_value(cmd, "--cap-drop") == "ALL"
    assert _flag_value(cmd, "--security-opt") == "no-new-privileges"
    assert _flag_value(cmd, "--memory") == "256m"
    assert _flag_value(cmd, "--memory-swap") == "256m"
    assert _flag_value(cmd, "--cpus") == "2.0"
    assert "--read-only" in cmd
    assert "A=b" in cmd
    assert cmd[-3:] == ["img:1", "echo", "hi"]


def test_empty_argv_rejected(tmp_path: Path) -> None:
    runner = SandboxRunner(SandboxPolicy(image="img:1"))
    with pytest.raises(ValueError):
        runner.run(tmp_path, [])


@pytest.fixture(scope="module")
def runner() -> SandboxRunner:
    instance = SandboxRunner(SandboxPolicy(image="python:3.12-slim", timeout_s=60))
    instance.ensure_image()
    return instance


@pytest.mark.docker
@needs_docker
def test_echo(runner: SandboxRunner, tmp_path: Path) -> None:
    record = runner.run(tmp_path, ["echo", "hello"])
    assert record.exit_code == 0
    assert record.stdout == "hello\n"
    assert not record.timed_out


@pytest.mark.docker
@needs_docker
def test_network_is_blocked(runner: SandboxRunner, tmp_path: Path) -> None:
    script = "import socket; socket.create_connection(('1.1.1.1', 53), timeout=3)"
    record = runner.run(tmp_path, ["python", "-c", script])
    assert record.exit_code != 0


@pytest.mark.docker
@needs_docker
def test_root_filesystem_is_read_only(runner: SandboxRunner, tmp_path: Path) -> None:
    record = runner.run(tmp_path, ["sh", "-c", "touch /etc/tribunal-probe"])
    assert record.exit_code != 0


@pytest.mark.docker
@needs_docker
def test_workspace_is_writable(runner: SandboxRunner, tmp_path: Path) -> None:
    record = runner.run(tmp_path, ["sh", "-c", "echo hi > out.txt"])
    assert record.exit_code == 0
    assert (tmp_path / "out.txt").read_text() == "hi\n"


@pytest.mark.docker
@needs_docker
def test_timeout_kills_container(runner: SandboxRunner, tmp_path: Path) -> None:
    record = runner.run(tmp_path, ["sleep", "30"], timeout_s=2)
    assert record.timed_out
    assert record.exit_code is None
