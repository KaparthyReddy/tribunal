import subprocess
from pathlib import Path

import pytest

from tribunal.envbuild import (
    DEFAULT_BASE_IMAGE,
    ENV_PREFIX,
    EnvBuildError,
    build_environment,
    collect_requirements,
    dockerfile,
    env_tag,
    normalize_name,
)


def _write(root: Path, files: dict[str, str]) -> Path:
    for relative, content in files.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
    return root


class Docker:
    def __init__(self, *, exists: bool = False, build_code: int = 0, build_err: str = "") -> None:
        self.exists = exists
        self.build_code = build_code
        self.build_err = build_err
        self.calls: list[list[str]] = []
        self.contexts: list[dict[str, str]] = []

    def __call__(self, argv: list[str], timeout_s: int) -> subprocess.CompletedProcess[str]:
        self.calls.append(argv)
        if argv[:3] == ["docker", "image", "inspect"]:
            return subprocess.CompletedProcess(argv, 0 if self.exists else 1, "", "")
        context = Path(argv[-1])
        self.contexts.append(
            {
                "requirements": (context / "requirements.txt").read_text(),
                "dockerfile": (context / "Dockerfile").read_text(),
            }
        )
        return subprocess.CompletedProcess(argv, self.build_code, "", self.build_err)


def test_plain_requirements_are_parsed_sorted_and_cleaned(tmp_path: Path) -> None:
    root = _write(
        tmp_path,
        {
            "requirements.txt": (
                "requests>=2.0,<3  # http\n\n# comment\npytest\n"
                "numpy==1.26.4 ; python_version < '3.13'\nPackage_Name[extra1, extra2]>=1\n"
            )
        },
    )
    collected = collect_requirements(root)
    assert list(collected.requirements) == [
        "numpy==1.26.4 ; python_version < '3.13'",
        "Package_Name[extra1, extra2]>=1",
        "pytest",
        "requests>=2.0,<3",
    ]
    assert collected.sources == ("requirements.txt",)
    assert collected.skipped == ()


def test_lines_that_are_not_plain_specifiers_are_skipped(tmp_path: Path) -> None:
    root = _write(
        tmp_path,
        {
            "requirements.txt": (
                "-e .\n./local\ngit+https://github.com/x/y.git\n"
                "pkg @ https://example.com/pkg.whl\n--index-url https://pypi.example/simple\n"
                "-c constraints.txt\nok==1\n"
            )
        },
    )
    collected = collect_requirements(root)
    assert list(collected.requirements) == ["ok==1"]
    assert len(collected.skipped) == 6


def test_line_continuations_are_joined(tmp_path: Path) -> None:
    root = _write(tmp_path, {"requirements.txt": "pkg>=1,\\\n    <2\n"})
    assert list(collect_requirements(root).requirements) == ["pkg>=1, <2"]


def test_includes_are_followed_relative_to_the_including_file(tmp_path: Path) -> None:
    root = _write(
        tmp_path,
        {
            "requirements/dev.txt": "-r base.txt\npytest\n",
            "requirements/base.txt": "flask==3.0\n",
        },
    )
    collected = collect_requirements(root, requirements_files=["requirements/dev.txt"])
    assert list(collected.requirements) == ["flask==3.0", "pytest"]
    assert collected.sources == ("requirements/dev.txt", "requirements/base.txt")


def test_includes_outside_the_repository_are_refused(tmp_path: Path) -> None:
    root = _write(tmp_path / "repo", {"requirements.txt": "-r ../outside.txt\nok==1\n"})
    _write(tmp_path, {"outside.txt": "evil==1\n"})
    collected = collect_requirements(root)
    assert list(collected.requirements) == ["ok==1"]
    assert any("unsafe" in note for note in collected.skipped)


def test_include_cycles_terminate(tmp_path: Path) -> None:
    root = _write(tmp_path, {"a.txt": "-r b.txt\nx==1\n", "b.txt": "-r a.txt\ny==1\n"})
    collected = collect_requirements(root, requirements_files=["a.txt"])
    assert list(collected.requirements) == ["x==1", "y==1"]


def test_a_missing_requested_file_is_reported(tmp_path: Path) -> None:
    collected = collect_requirements(tmp_path, requirements_files=["nope.txt"])
    assert collected.requirements == ()
    assert collected.skipped == ("nope.txt: not found",)


PYPROJECT = """
[project]
name = "My-Pkg"
dependencies = ["httpx>=0.27", "my_pkg[extra]"]

[project.optional-dependencies]
test = ["pytest>=8"]
docs = ["sphinx"]

[dependency-groups]
dev = ["ruff", {include-group = "lint"}]
lint = ["black==24.1.0"]
"""


def test_pyproject_defaults_pick_dev_and_test_names(tmp_path: Path) -> None:
    root = _write(tmp_path, {"pyproject.toml": PYPROJECT})
    collected = collect_requirements(root)
    assert list(collected.requirements) == ["black==24.1.0", "httpx>=0.27", "pytest>=8", "ruff"]
    assert collected.sources == ("pyproject.toml",)
    assert any("(the project itself)" in note for note in collected.skipped)


def test_pyproject_explicit_selection(tmp_path: Path) -> None:
    root = _write(tmp_path, {"pyproject.toml": PYPROJECT})
    collected = collect_requirements(root, extras=["docs"], groups=["lint"])
    assert list(collected.requirements) == ["black==24.1.0", "httpx>=0.27", "sphinx"]


def test_pyproject_unknown_extras_and_groups_are_reported(tmp_path: Path) -> None:
    root = _write(tmp_path, {"pyproject.toml": PYPROJECT})
    collected = collect_requirements(root, extras=["nope"], groups=["gone"])
    assert "pyproject.toml: no extra named nope" in collected.skipped
    assert "pyproject.toml: no dependency group named gone" in collected.skipped


def test_a_broken_pyproject_does_not_hide_requirements_files(tmp_path: Path) -> None:
    root = _write(tmp_path, {"pyproject.toml": "not toml [", "requirements.txt": "ok==1\n"})
    collected = collect_requirements(root)
    assert list(collected.requirements) == ["ok==1"]
    assert collected.skipped == ("pyproject.toml: could not be parsed",)


def test_duplicates_are_removed_case_insensitively(tmp_path: Path) -> None:
    root = _write(tmp_path, {"requirements.txt": "a==1\nA==1\na==1\n"})
    assert list(collect_requirements(root).requirements) == ["a==1"]


def test_too_many_requirements_are_refused(tmp_path: Path) -> None:
    root = _write(tmp_path, {"requirements.txt": "\n".join(f"pkg{i}==1" for i in range(501))})
    with pytest.raises(EnvBuildError, match="limit"):
        collect_requirements(root)


def test_normalize_name() -> None:
    assert normalize_name("My_Pkg[extra]>=1") == "my-pkg"
    assert normalize_name("") == ""


def test_tags_are_content_addressed() -> None:
    tag = env_tag("python:3.12-slim", ["a==1"], False)
    assert tag.startswith(ENV_PREFIX)
    assert len(tag) == len(ENV_PREFIX) + 12
    assert tag == env_tag("python:3.12-slim", ["a==1"], False)
    assert tag != env_tag("python:3.11-slim", ["a==1"], False)
    assert tag != env_tag("python:3.12-slim", ["a==2"], False)
    assert tag != env_tag("python:3.12-slim", ["a==1"], True)


def test_dockerfile_flags() -> None:
    text = dockerfile("python:3.12-slim")
    assert text.startswith("FROM python:3.12-slim\n")
    assert "ENV PYTHONPATH=/work:/work/src" in text
    assert "--only-binary=:all:" in text
    assert "--only-binary" not in dockerfile("x", allow_sdist=True)


def test_build_uses_the_requested_commit(make_repo) -> None:
    repo, shas = make_repo([{"requirements.txt": "a==1\n"}, {"requirements.txt": "b==2\n"}])
    docker = Docker()
    environment = build_environment(repo, shas[0], execute=docker)

    assert environment.status == "built"
    assert environment.requirements == ("a==1",)
    assert environment.image == env_tag(DEFAULT_BASE_IMAGE, ["a==1"], False)
    assert docker.contexts[0]["requirements"] == "a==1\n"
    build = docker.calls[-1]
    assert build[:2] == ["docker", "build"]
    assert environment.image in build
    assert any(arg.startswith("tribunal.requirements=") for arg in build)


def test_an_existing_image_is_reused(make_repo) -> None:
    repo, shas = make_repo([{"requirements.txt": "a==1\n"}])
    docker = Docker(exists=True)
    environment = build_environment(repo, shas[0], execute=docker)
    assert environment.status == "cached"
    assert docker.contexts == []


def test_force_rebuilds_an_existing_image(make_repo) -> None:
    repo, shas = make_repo([{"requirements.txt": "a==1\n"}])
    docker = Docker(exists=True)
    environment = build_environment(repo, shas[0], force=True, execute=docker)
    assert environment.status == "built"
    assert len(docker.contexts) == 1


def test_no_dependencies_means_the_base_image_and_no_docker_calls(make_repo) -> None:
    repo, shas = make_repo([{"main.py": "x = 1\n"}])
    docker = Docker()
    environment = build_environment(repo, shas[0], base_image="python:3.11-slim", execute=docker)
    assert environment.status == "base"
    assert environment.image == "python:3.11-slim"
    assert docker.calls == []


def test_unpinned_dependencies_are_counted(make_repo) -> None:
    repo, shas = make_repo([{"requirements.txt": "a==1\nb>=2\nc\nd~=3.1\n"}])
    environment = build_environment(repo, shas[0], execute=Docker())
    assert environment.unpinned == 3
    assert environment.as_dict()["unpinned"] == 3


def test_build_failure_explains_source_builds(make_repo) -> None:
    repo, shas = make_repo([{"requirements.txt": "a==1\n"}])
    failing = Docker(build_code=1, build_err="ERROR: No matching distribution found for a")
    with pytest.raises(EnvBuildError, match="--allow-sdist"):
        build_environment(repo, shas[0], execute=failing)
    with pytest.raises(EnvBuildError) as info:
        build_environment(repo, shas[0], allow_sdist=True, execute=failing)
    assert "--allow-sdist" not in str(info.value)
    assert "--only-binary" not in failing.contexts[-1]["dockerfile"]


def test_invalid_input_is_rejected(make_repo) -> None:
    repo, shas = make_repo([{"requirements.txt": "a==1\n"}])
    for bad in ("python:3.12\nRUN evil", "bad image", ""):
        with pytest.raises(EnvBuildError, match="base image"):
            build_environment(repo, shas[0], base_image=bad, execute=Docker())
    with pytest.raises(EnvBuildError):
        build_environment(repo, "nope", execute=Docker())
