import subprocess
import sys
from pathlib import Path

import pytest

from benchmark.cases import ALL_CASES, HOLDOUT2_CASES, HOLDOUT_CASES
from benchmark.model import build_repo
from tribunal.sandbox import materialize


def _unittest_exit_code(directory: Path) -> int:
    result = subprocess.run(
        [sys.executable, "-m", "unittest"],
        cwd=directory,
        capture_output=True,
        text=True,
        timeout=60,
    )
    return result.returncode


def test_holdout2_inventory() -> None:
    assert len(HOLDOUT2_CASES) == 17
    assert sum(1 for case in HOLDOUT2_CASES if case.expect == "buggy") == 11
    assert sum(1 for case in HOLDOUT2_CASES if case.expect == "clean") == 6
    assert all(case.id.startswith("h2-") for case in HOLDOUT2_CASES)
    other_ids = {case.id for case in [*ALL_CASES, *HOLDOUT_CASES]}
    assert other_ids.isdisjoint({case.id for case in HOLDOUT2_CASES})
    assert [case.id for case in HOLDOUT2_CASES if case.tests_catch] == ["h2-tests-catch-it"]


@pytest.mark.parametrize("case", HOLDOUT2_CASES, ids=lambda case: case.id)
def test_holdout2_case_behaves_as_declared(case, tmp_path: Path) -> None:
    repo, base_sha, head_sha = build_repo(case, tmp_path / "repos")
    base_dir = tmp_path / "base"
    head_dir = tmp_path / "head"
    materialize(repo, base_sha, base_dir)
    materialize(repo, head_sha, head_dir)

    assert _unittest_exit_code(base_dir) == 0
    head_code = _unittest_exit_code(head_dir)
    if case.tests_catch:
        assert head_code != 0
    else:
        assert head_code == 0
