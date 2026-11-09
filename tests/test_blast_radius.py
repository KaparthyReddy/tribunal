from pathlib import Path

from tribunal.agents import BlastRadius
from tribunal.models import Severity


def _write(root: Path, files: dict[str, str]) -> None:
    for relative, content in files.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)


def _titles(result) -> list[str]:
    return [f.title for f in result.findings]


def test_uncovered_function_is_flagged(tmp_path: Path) -> None:
    _write(
        tmp_path,
        {
            "lib.py": (
                "def covered():\n    return 1\n\n\ndef uncovered():\n    return 2\n"
            ),
            "test_lib.py": (
                "from lib import covered\n\n\ndef test_covered():\n    assert covered() == 1\n"
            ),
        },
    )
    result = BlastRadius().analyze(tmp_path, {"lib.py": [(1, 2), (5, 6)]})
    titles = _titles(result)
    assert any("No test reaches changed code: uncovered" in t for t in titles)
    assert not any("No test reaches changed code: covered" in t for t in titles)
    flagged = [f for f in result.findings if "uncovered" in f.title]
    assert flagged[0].severity is Severity.MEDIUM


def test_transitive_coverage(tmp_path: Path) -> None:
    _write(
        tmp_path,
        {
            "lib.py": "def leaf():\n    return 1\n\n\ndef mid():\n    return leaf()\n",
            "test_lib.py": "from lib import mid\n\n\ndef test_mid():\n    assert mid() == 1\n",
        },
    )
    result = BlastRadius().analyze(tmp_path, {"lib.py": [(1, 2)]})
    assert result.findings == []


def test_many_dependents_without_tests_is_high(tmp_path: Path) -> None:
    source = "def core():\n    return 1\n" + "".join(
        f"\n\ndef user{i}():\n    return core()\n" for i in range(5)
    )
    _write(tmp_path, {"lib.py": source})
    result = BlastRadius().analyze(tmp_path, {"lib.py": [(1, 2)]})
    assert result.findings[0].severity is Severity.HIGH


def test_wide_blast_radius(tmp_path: Path) -> None:
    source = "def core():\n    return 1\n" + "".join(
        f"\n\ndef user{i}():\n    return core()\n" for i in range(3)
    )
    _write(
        tmp_path,
        {
            "lib.py": source,
            "test_lib.py": "from lib import core\n\n\ndef test_core():\n    assert core() == 1\n",
        },
    )
    result = BlastRadius(wide_threshold=2).analyze(tmp_path, {"lib.py": [(1, 2)]})
    assert any("Wide blast radius" in t for t in _titles(result))
    assert not any("No test reaches" in t for t in _titles(result))


def test_changed_test_files_are_ignored(tmp_path: Path) -> None:
    _write(
        tmp_path,
        {"test_lib.py": "def test_a():\n    assert True\n"},
    )
    result = BlastRadius().analyze(tmp_path, {"test_lib.py": [(1, 2)]})
    assert result.findings == []


def test_non_python_files_noted(tmp_path: Path) -> None:
    result = BlastRadius().analyze(tmp_path, {"README.md": [(1, 1)], "x.toml": [(2, 2)]})
    assert result.findings[0].severity is Severity.INFO
    assert "2 non-Python" in result.findings[0].title


def test_module_level_change_is_info(tmp_path: Path) -> None:
    _write(tmp_path, {"lib.py": "VALUE = 1\n\n\ndef f():\n    return VALUE\n"})
    result = BlastRadius().analyze(tmp_path, {"lib.py": [(1, 1)]})
    assert [f.severity for f in result.findings] == [Severity.INFO]
