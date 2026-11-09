import os
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

import tree_sitter_python as tspython
from tree_sitter import Language, Node, Parser

MODULE = "<module>"
MAX_AMBIGUITY = 5
MAX_LINES_PER_RANGE = 2000
IGNORED_DIRS = frozenset(
    {
        ".git",
        ".hg",
        ".venv",
        "venv",
        "env",
        "node_modules",
        "__pycache__",
        ".tox",
        ".mypy_cache",
        ".pytest_cache",
        "build",
        "dist",
        "site-packages",
    }
)

_LANGUAGE = Language(tspython.language())


@dataclass(frozen=True)
class Symbol:
    file: str
    qualname: str
    name: str
    start: int
    end: int

    @property
    def key(self) -> str:
        return f"{self.file}::{self.qualname}"

    @property
    def is_module(self) -> bool:
        return self.qualname == MODULE


@dataclass
class ParsedFile:
    file: str
    symbols: list[Symbol]
    calls: dict[str, set[str]]
    aliases: dict[str, list[str]] = field(default_factory=dict)
    blank_lines: frozenset[int] = frozenset()


def is_test_file(path: str) -> bool:
    pure = PurePosixPath(path)
    name = pure.name
    if name == "conftest.py" or name.startswith("test_") or name.endswith("_test.py"):
        return True
    return any(part in {"tests", "test"} for part in pure.parts[:-1])


def _text(node: Node | None) -> str | None:
    if node is None or node.text is None:
        return None
    return node.text.decode("utf-8", "replace")


def _callee_name(node: Node | None) -> str | None:
    if node is None:
        return None
    if node.type == "identifier":
        return _text(node)
    if node.type == "attribute":
        return _text(node.child_by_field_name("attribute"))
    return None


def _walk(node: Node, scope: list[str], current: str, parsed: ParsedFile) -> None:
    for child in node.children:
        kind = child.type
        if kind == "function_definition":
            name = _text(child.child_by_field_name("name"))
            body = child.child_by_field_name("body")
            if name is None or body is None:
                continue
            symbol = Symbol(
                file=parsed.file,
                qualname=".".join([*scope, name]),
                name=name,
                start=child.start_point[0] + 1,
                end=child.end_point[0] + 1,
            )
            parsed.symbols.append(symbol)
            parsed.calls.setdefault(symbol.key, set())
            if name == "__init__" and scope:
                parsed.aliases.setdefault(scope[-1], []).append(symbol.key)
            _walk(body, [*scope, name], symbol.key, parsed)
        elif kind == "class_definition":
            name = _text(child.child_by_field_name("name"))
            body = child.child_by_field_name("body")
            if name is None or body is None:
                continue
            _walk(body, [*scope, name], current, parsed)
        elif kind == "call":
            callee = _callee_name(child.child_by_field_name("function"))
            if callee:
                parsed.calls[current].add(callee)
            _walk(child, scope, current, parsed)
        else:
            _walk(child, scope, current, parsed)


def parse_python(file: str, source: bytes) -> ParsedFile:
    tree = Parser(_LANGUAGE).parse(source)
    module = Symbol(
        file=file,
        qualname=MODULE,
        name=MODULE,
        start=1,
        end=source.count(b"\n") + 1,
    )
    blank = frozenset(
        index + 1
        for index, line in enumerate(source.splitlines())
        if not line.strip() or line.lstrip().startswith(b"#")
    )
    parsed = ParsedFile(
        file=file,
        symbols=[module],
        calls={module.key: set()},
        blank_lines=blank,
    )
    try:
        _walk(tree.root_node, [], module.key, parsed)
    except RecursionError:
        pass
    return parsed


class CallGraph:
    def __init__(self, files: dict[str, ParsedFile]) -> None:
        self.files = files
        self.symbols: dict[str, Symbol] = {}
        self._by_file: dict[str, list[Symbol]] = {}
        self.callers: dict[str, set[str]] = {}

        by_name: dict[str, list[Symbol]] = {}
        aliases: dict[str, list[str]] = {}
        for parsed in files.values():
            self._by_file[parsed.file] = [s for s in parsed.symbols if not s.is_module]
            for symbol in parsed.symbols:
                self.symbols[symbol.key] = symbol
                if not symbol.is_module:
                    by_name.setdefault(symbol.name, []).append(symbol)
            for class_name, keys in parsed.aliases.items():
                aliases.setdefault(class_name, []).extend(keys)

        for parsed in files.values():
            for caller_key, names in parsed.calls.items():
                for name in names:
                    targets = list(by_name.get(name, []))
                    targets.extend(self.symbols[key] for key in aliases.get(name, []))
                    if not targets or len(targets) > MAX_AMBIGUITY:
                        continue
                    for target in targets:
                        self.callers.setdefault(target.key, set()).add(caller_key)

    def symbol_at_line(self, file: str, line: int) -> Symbol:
        best: Symbol | None = None
        for symbol in self._by_file.get(file, []):
            if symbol.start <= line <= symbol.end and (
                best is None or symbol.end - symbol.start < best.end - best.start
            ):
                best = symbol
        return best or self.symbols[f"{file}::{MODULE}"]

    def symbols_in(self, file: str, start: int, end: int) -> list[Symbol]:
        parsed = self.files.get(file)
        if parsed is None:
            return []
        found: dict[str, Symbol] = {}
        last = min(end, start + MAX_LINES_PER_RANGE)
        for line in range(start, last + 1):
            if line in parsed.blank_lines:
                continue
            symbol = self.symbol_at_line(file, line)
            found[symbol.key] = symbol
        return list(found.values())

    def callers_closure(self, key: str, depth: int) -> dict[str, int]:
        seen = {key: 0}
        queue = deque([key])
        while queue:
            current = queue.popleft()
            if seen[current] >= depth:
                continue
            for caller in self.callers.get(current, ()):
                if caller not in seen:
                    seen[caller] = seen[current] + 1
                    queue.append(caller)
        seen.pop(key)
        return seen


def build_callgraph(root: Path, max_files: int = 2000, max_bytes: int = 500_000) -> CallGraph:
    files: dict[str, ParsedFile] = {}
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(
            d for d in dirnames if d not in IGNORED_DIRS and not d.endswith(".egg-info")
        )
        for filename in sorted(filenames):
            if not filename.endswith(".py"):
                continue
            full = Path(dirpath) / filename
            try:
                if full.stat().st_size > max_bytes:
                    continue
                data = full.read_bytes()
            except OSError:
                continue
            relative = full.relative_to(root).as_posix()
            files[relative] = parse_python(relative, data)
            if len(files) >= max_files:
                return CallGraph(files)
    return CallGraph(files)
