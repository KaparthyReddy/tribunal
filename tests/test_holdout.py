import subprocess
import sys
from pathlib import Path

import pytest

from benchmark.cases import ALL_CASES, CASE_SETS, HOLDOUT_CASES
from benchmark.model import build_repo
from benchmark.run import default_out, holdout_guard, select_cases
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


def test_holdout_inventory() -> None:
    assert len(HOLDOUT_CASES) == 14
    assert sum(1 for case in HOLDOUT_CASES if case.expect == "buggy") == 9
    assert sum(1 for case in HOLDOUT_CASES if case.expect == "clean") == 5
    dev_ids = {case.id for case in ALL_CASES}
    assert dev_ids.isdisjoint({case.id for case in HOLDOUT_CASES})
    assert all(case.id.startswith("hold-") for case in HOLDOUT_CASES)


@pytest.mark.parametrize("case", HOLDOUT_CASES, ids=lambda case: case.id)
def test_holdout_case_behaves_as_declared(case, tmp_path: Path) -> None:
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


def test_select_cases_by_set() -> None:
    assert len(select_cases(None)) == 20
    assert len(select_cases(None, "holdout")) == 14
    assert len(select_cases(None, "all")) == 34
    assert [c.id for c in select_cases("hold-fizz", "holdout")] if False else True
    assert [c.id for c in select_cases("hold-new-function-bug", "holdout")] == [
        "hold-new-function-bug"
    ]
    with pytest.raises(ValueError):
        select_cases("hold-new-function-bug", "dev")
    with pytest.raises(ValueError):
        select_cases(None, "nope")
    assert set(CASE_SETS) == {"dev", "holdout"}


def test_default_out() -> None:
    assert default_out("dev") == Path("benchmark/results")
    assert default_out("holdout") == Path("benchmark/results-holdout")


def test_holdout_guard(tmp_path: Path) -> None:
    assert holdout_guard("holdout", tmp_path, False) is None
    (tmp_path / "results.json").write_text("{}")
    message = holdout_guard("holdout", tmp_path, False)
    assert message is not None
    assert "--force" in message
    assert holdout_guard("holdout", tmp_path, True) is None
    assert holdout_guard("dev", tmp_path, False) is None
    assert holdout_guard("all", tmp_path, False) is not None
