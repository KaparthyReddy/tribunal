from pathlib import Path

import pytest

from tribunal.graph import CallGraph, build_callgraph, is_test_file, parse_python

LINES = [
    "def helper(x):",
    "    return x + 1",
    "",
    "",
    "class Box:",
    "    def __init__(self, v):",
    "        self.v = helper(v)",
    "",
    "    def get(self):",
    "        return self.v",
    "",
    "",
    "def run():",
    "    b = Box(1)",
    "    return b.get()",
]
SOURCE = ("\n".join(LINES) + "\n").encode()


def line_of(text: str) -> int:
    return LINES.index(text) + 1


def _write(root: Path, files: dict[str, str]) -> None:
    for relative, content in files.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)


def test_symbols_and_calls() -> None:
    parsed = parse_python("a.py", SOURCE)
    assert {s.qualname for s in parsed.symbols} == {
        "<module>",
        "helper",
        "Box.__init__",
        "Box.get",
        "run",
    }
    assert parsed.calls["a.py::run"] == {"Box", "get"}
    assert parsed.calls["a.py::Box.__init__"] == {"helper"}
    assert parsed.aliases == {"Box": ["a.py::Box.__init__"]}


def test_decorated_and_async() -> None:
    parsed = parse_python("b.py", b"@deco(1)\nasync def fetch():\n    return await other()\n")
    assert "fetch" in {s.qualname for s in parsed.symbols}
    assert parsed.calls["b.py::fetch"] == {"other"}
    assert parsed.calls["b.py::<module>"] == {"deco"}


def test_constructor_resolves_to_init() -> None:
    graph = CallGraph({"a.py": parse_python("a.py", SOURCE)})
    assert "a.py::run" in graph.callers["a.py::Box.__init__"]
    assert "a.py::Box.__init__" in graph.callers["a.py::helper"]


def test_symbols_in_maps_lines() -> None:
    graph = CallGraph({"a.py": parse_python("a.py", SOURCE)})

    def names(start: int, end: int) -> set[str]:
        return {s.qualname for s in graph.symbols_in("a.py", start, end)}

    body = line_of("    return x + 1")
    assert names(body, body) == {"helper"}
    init_body = line_of("        self.v = helper(v)")
    assert names(init_body, init_body) == {"Box.__init__"}
    klass = line_of("class Box:")
    assert names(klass, klass) == {"<module>"}
    assert names(3, 4) == set()
    assert names(1, len(LINES)) == {"<module>", "helper", "Box.__init__", "Box.get", "run"}
    assert graph.symbols_in("missing.py", 1, 5) == []


def test_callers_closure_across_files(tmp_path: Path) -> None:
    _write(
        tmp_path,
        {
            "lib.py": "def leaf():\n    return 1\n\n\ndef mid():\n    return leaf()\n",
            "test_lib.py": "from lib import mid\n\n\ndef test_mid():\n    assert mid() == 1\n",
        },
    )
    graph = build_callgraph(tmp_path)
    assert graph.callers_closure("lib.py::leaf", 4) == {
        "lib.py::mid": 1,
        "test_lib.py::test_mid": 2,
    }
    assert graph.callers_closure("lib.py::leaf", 1) == {"lib.py::mid": 1}


def test_build_skips_ignored_dirs(tmp_path: Path) -> None:
    _write(tmp_path, {".venv/x.py": "def z():\n    pass\n", "src/a.py": "def a():\n    pass\n"})
    graph = build_callgraph(tmp_path)
    assert set(graph.files) == {"src/a.py"}


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("tests/test_x.py", True),
        ("pkg/test_x.py", True),
        ("pkg/x_test.py", True),
        ("conftest.py", True),
        ("pkg/test/helpers.py", True),
        ("pkg/core.py", False),
        ("src/contest.py", False),
    ],
)
def test_is_test_file(path: str, expected: bool) -> None:
    assert is_test_file(path) is expected
