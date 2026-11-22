import hashlib
import posixpath
import re
import subprocess
import tempfile
import tomllib
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Literal

from tribunal.sandbox import WorkspaceError, resolve_sha, workspace

DEFAULT_BASE_IMAGE = "python:3.12-slim"
ENV_PREFIX = "tribunal-env:"
LABEL = "tribunal.requirements"
AUTO_REQUIREMENT_FILES = (
    "requirements.txt",
    "requirements-dev.txt",
    "requirements_dev.txt",
    "requirements-test.txt",
    "dev-requirements.txt",
    "test-requirements.txt",
    "requirements/dev.txt",
    "requirements/test.txt",
)
AUTO_NAMES = ("dev", "test", "tests")
MAX_INCLUDE_DEPTH = 5
MAX_REQUIREMENTS = 500
MAX_FILE_BYTES = 200_000
BUILD_TIMEOUT_S = 1800
TAIL_CHARS = 2000

_VERSION = r"(?:===|==|~=|!=|<=|>=|<|>)\s*[A-Za-z0-9.*+!_-]+"
REQUIREMENT = re.compile(
    r"[A-Za-z0-9](?:[A-Za-z0-9._-]*[A-Za-z0-9])?"
    r"(?:\s*\[[A-Za-z0-9._,\s-]+\])?"
    rf"(?:\s*{_VERSION}(?:\s*,\s*{_VERSION})*)?"
    r"(?:\s*;\s*[^#]+)?"
)
IMAGE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._/:@-]*")
COMMENT = re.compile(r"(^|\s)#.*$")
INCLUDE = re.compile(r"(?:-r\s*|--requirement[\s=]+)(\S+)")
NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")

Execute = Callable[[list[str], int], "subprocess.CompletedProcess[str]"]


class EnvBuildError(RuntimeError):
    pass


@dataclass(frozen=True)
class Collected:
    requirements: tuple[str, ...]
    skipped: tuple[str, ...]
    sources: tuple[str, ...]


@dataclass(frozen=True)
class Environment:
    image: str
    status: Literal["built", "cached", "base"]
    base_image: str
    requirements: tuple[str, ...]
    skipped: tuple[str, ...]
    sources: tuple[str, ...]
    unpinned: int

    def as_dict(self) -> dict[str, object]:
        return {
            "image": self.image,
            "status": self.status,
            "base_image": self.base_image,
            "requirements": list(self.requirements),
            "skipped": list(self.skipped),
            "sources": list(self.sources),
            "unpinned": self.unpinned,
        }


def normalize_name(spec: str) -> str:
    match = NAME.match(spec)
    return re.sub(r"[-_.]+", "-", match.group(0)).lower() if match else ""


def _logical_lines(text: str) -> list[str]:
    lines: list[str] = []
    pending = ""
    for raw in text.splitlines():
        if raw.rstrip().endswith("\\"):
            pending += raw.rstrip()[:-1] + " "
            continue
        lines.append(pending + raw)
        pending = ""
    if pending:
        lines.append(pending)
    return lines


def _resolve(root: Path, relative: str) -> Path:
    pure = PurePosixPath(relative)
    if not relative or pure.is_absolute() or ".." in pure.parts or "\\" in relative:
        raise EnvBuildError(f"unsafe path {relative!r}")
    resolved_root = root.resolve()
    target = (resolved_root / Path(*pure.parts)).resolve()
    if not target.is_relative_to(resolved_root):
        raise EnvBuildError(f"unsafe path {relative!r}")
    return target


def _as_strings(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str)]


def _as_table(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


class _Collector:
    def __init__(self, project: str | None) -> None:
        self.project = project
        self.specs: list[str] = []
        self.skipped: list[str] = []
        self.sources: list[str] = []
        self._groups_seen: set[str] = set()

    def skip(self, message: str) -> None:
        self.skipped.append(message)

    def add(self, spec: str, origin: str) -> None:
        spec = " ".join(spec.split())
        if not REQUIREMENT.fullmatch(spec):
            self.skip(f"{origin}: {spec[:120]}")
        elif self.project and normalize_name(spec) == self.project:
            self.skip(f"{origin}: {spec[:120]} (the project itself)")
        else:
            self.specs.append(spec)

    def read_file(self, root: Path, relative: str, seen: set[str], depth: int) -> None:
        if depth > MAX_INCLUDE_DEPTH:
            self.skip(f"{relative}: includes are nested too deeply")
            return
        if relative in seen:
            return
        seen.add(relative)
        path = _resolve(root, relative)
        if not path.is_file():
            self.skip(f"{relative}: not found")
            return
        try:
            if path.stat().st_size > MAX_FILE_BYTES:
                self.skip(f"{relative}: file is too large")
                return
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            self.skip(f"{relative}: could not be read")
            return
        self.sources.append(relative)
        for raw in _logical_lines(text):
            line = COMMENT.sub("", raw).strip()
            if not line:
                continue
            include = INCLUDE.fullmatch(line)
            if include:
                nested = posixpath.normpath(
                    posixpath.join(posixpath.dirname(relative), include.group(1))
                )
                try:
                    self.read_file(root, nested, seen, depth + 1)
                except EnvBuildError as exc:
                    self.skip(f"{relative}: {exc}")
                continue
            if line.startswith("-"):
                self.skip(f"{relative}: {line[:120]}")
                continue
            self.add(line, relative)

    def read_group(self, table: dict[str, Any], name: str, depth: int) -> None:
        if depth > MAX_INCLUDE_DEPTH or name in self._groups_seen:
            return
        self._groups_seen.add(name)
        items = table.get(name)
        if not isinstance(items, list):
            self.skip(f"pyproject.toml: no dependency group named {name}")
            return
        for item in items:
            if isinstance(item, str):
                self.add(item, f"dependency-groups.{name}")
            elif isinstance(item, dict) and isinstance(item.get("include-group"), str):
                self.read_group(table, item["include-group"], depth + 1)

    def read_pyproject(
        self,
        data: dict[str, Any],
        extras: Sequence[str] | None,
        groups: Sequence[str] | None,
    ) -> None:
        self.sources.append("pyproject.toml")
        project = _as_table(data.get("project"))
        for spec in _as_strings(project.get("dependencies")):
            self.add(spec, "pyproject.toml")

        optional = _as_table(project.get("optional-dependencies"))
        for name in list(extras) if extras else [n for n in AUTO_NAMES if n in optional]:
            if name not in optional:
                self.skip(f"pyproject.toml: no extra named {name}")
                continue
            for spec in _as_strings(optional[name]):
                self.add(spec, f"optional-dependencies.{name}")

        table = _as_table(data.get("dependency-groups"))
        for name in list(groups) if groups else [n for n in AUTO_NAMES if n in table]:
            self.read_group(table, name, 0)


def _load_pyproject(root: Path) -> tuple[dict[str, Any] | None, str | None]:
    path = root / "pyproject.toml"
    if not path.is_file():
        return None, None
    try:
        return tomllib.loads(path.read_text(encoding="utf-8")), None
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError):
        return None, "pyproject.toml: could not be parsed"


def _finalize(specs: list[str]) -> list[str]:
    unique: dict[str, str] = {}
    for spec in specs:
        unique.setdefault(spec.lower(), spec)
    return sorted(unique.values(), key=str.lower)


def collect_requirements(
    root: Path,
    *,
    requirements_files: Sequence[str] | None = None,
    extras: Sequence[str] | None = None,
    groups: Sequence[str] | None = None,
) -> Collected:
    pyproject, problem = _load_pyproject(root)
    project = _as_table(pyproject.get("project")) if pyproject else {}
    collector = _Collector(normalize_name(str(project.get("name", ""))) or None)
    if problem:
        collector.skip(problem)

    if requirements_files:
        files = list(requirements_files)
    else:
        files = [name for name in AUTO_REQUIREMENT_FILES if (root / name).is_file()]
    seen: set[str] = set()
    for relative in files:
        try:
            collector.read_file(root, posixpath.normpath(relative), seen, 0)
        except EnvBuildError as exc:
            collector.skip(f"{relative}: {exc}")
    if pyproject is not None:
        collector.read_pyproject(pyproject, extras, groups)

    requirements = _finalize(collector.specs)
    if len(requirements) > MAX_REQUIREMENTS:
        raise EnvBuildError(f"{len(requirements)} dependencies is more than the limit of {MAX_REQUIREMENTS}")
    return Collected(tuple(requirements), tuple(collector.skipped), tuple(collector.sources))


def count_unpinned(requirements: Sequence[str]) -> int:
    return sum(1 for spec in requirements if not re.search(r"===?", spec.split(";")[0]))


def requirements_text(requirements: Sequence[str]) -> str:
    return "\n".join(requirements) + "\n"


def _digest(base_image: str, requirements: Sequence[str], allow_sdist: bool) -> str:
    payload = "\n".join([base_image, f"allow_sdist={allow_sdist}", *requirements])
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def env_tag(base_image: str, requirements: Sequence[str], allow_sdist: bool = False) -> str:
    return f"{ENV_PREFIX}{_digest(base_image, requirements, allow_sdist)[:12]}"


def dockerfile(base_image: str, allow_sdist: bool = False) -> str:
    flag = "" if allow_sdist else " --only-binary=:all:"
    return (
        f"FROM {base_image}\n"
        "ENV PYTHONPATH=/work:/work/src\n"
        "COPY requirements.txt /tmp/requirements.txt\n"
        f"RUN pip install --no-cache-dir --disable-pip-version-check{flag} "
        "-r /tmp/requirements.txt && rm /tmp/requirements.txt\n"
    )


def _execute(argv: list[str], timeout_s: int) -> "subprocess.CompletedProcess[str]":
    try:
        return subprocess.run(argv, capture_output=True, text=True, timeout=timeout_s)
    except FileNotFoundError as exc:
        raise EnvBuildError("docker executable not found") from exc
    except subprocess.TimeoutExpired as exc:
        raise EnvBuildError(f"docker timed out after {timeout_s}s") from exc


def _image_exists(tag: str, execute: Execute) -> bool:
    return execute(["docker", "image", "inspect", tag], 60).returncode == 0


def _build(
    tag: str,
    base_image: str,
    requirements: Sequence[str],
    allow_sdist: bool,
    execute: Execute,
    timeout_s: int,
) -> None:
    digest = _digest(base_image, requirements, allow_sdist)
    with tempfile.TemporaryDirectory(prefix="tribunal-env-") as tmp:
        context = Path(tmp)
        (context / "requirements.txt").write_text(requirements_text(requirements), encoding="utf-8")
        (context / "Dockerfile").write_text(dockerfile(base_image, allow_sdist), encoding="utf-8")
        result = execute(
            [
                "docker",
                "build",
                "--tag",
                tag,
                "--label",
                f"{LABEL}={digest}",
                "--file",
                str(context / "Dockerfile"),
                str(context),
            ],
            timeout_s,
        )
    if result.returncode != 0:
        tail = ((result.stderr or "") + (result.stdout or ""))[-TAIL_CHARS:]
        hint = ""
        if not allow_sdist and "No matching distribution" in tail:
            hint = "\nA package without a wheel needs --allow-sdist, which runs its build script."
        raise EnvBuildError(f"docker build failed:\n{tail}{hint}")


def build_environment(
    repo_path: str | Path,
    ref: str,
    *,
    base_image: str = DEFAULT_BASE_IMAGE,
    requirements_files: Sequence[str] | None = None,
    extras: Sequence[str] | None = None,
    groups: Sequence[str] | None = None,
    allow_sdist: bool = False,
    force: bool = False,
    execute: Execute = _execute,
    timeout_s: int = BUILD_TIMEOUT_S,
) -> Environment:
    if not IMAGE.fullmatch(base_image):
        raise EnvBuildError(f"invalid base image {base_image!r}")
    repo = Path(repo_path).expanduser().resolve()
    try:
        sha = resolve_sha(repo, ref)
        with workspace(repo, sha) as root:
            collected = collect_requirements(
                root, requirements_files=requirements_files, extras=extras, groups=groups
            )
    except WorkspaceError as exc:
        raise EnvBuildError(str(exc)) from exc

    unpinned = count_unpinned(collected.requirements)

    def result(image: str, status: Literal["built", "cached", "base"]) -> Environment:
        return Environment(
            image=image,
            status=status,
            base_image=base_image,
            requirements=collected.requirements,
            skipped=collected.skipped,
            sources=collected.sources,
            unpinned=unpinned,
        )

    if not collected.requirements:
        return result(base_image, "base")

    tag = env_tag(base_image, collected.requirements, allow_sdist)
    if not force and _image_exists(tag, execute):
        return result(tag, "cached")
    _build(tag, base_image, collected.requirements, allow_sdist, execute, timeout_s)
    return result(tag, "built")
