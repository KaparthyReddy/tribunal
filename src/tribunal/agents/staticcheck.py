import ast

TRACKED = (
    ast.Expr,
    ast.Assign,
    ast.AugAssign,
    ast.AnnAssign,
    ast.Return,
    ast.Raise,
    ast.Assert,
    ast.Delete,
    ast.Import,
    ast.ImportFrom,
    ast.If,
    ast.For,
    ast.AsyncFor,
    ast.While,
    ast.With,
    ast.AsyncWith,
    ast.FunctionDef,
    ast.AsyncFunctionDef,
    ast.ClassDef,
    ast.ExceptHandler,
)
SCOPES = (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)


def _parse(source: str) -> ast.Module | None:
    try:
        return ast.parse(source)
    except (SyntaxError, ValueError):
        return None


def _is_string_statement(node: ast.AST) -> bool:
    return (
        isinstance(node, ast.Expr)
        and isinstance(node.value, ast.Constant)
        and isinstance(node.value.value, str)
    )


def _first_line(node: ast.AST) -> int:
    decorators = getattr(node, "decorator_list", None) or []
    return min([node.lineno, *(decorator.lineno for decorator in decorators)])


def statement_spans(source: str) -> list[tuple[int, int, int]] | None:
    tree = _parse(source)
    if tree is None:
        return None
    spans: list[tuple[int, int, int]] = []
    for node in ast.walk(tree):
        if not isinstance(node, TRACKED) or _is_string_statement(node):
            continue
        if isinstance(node, ast.AnnAssign) and node.value is None:
            continue
        end = getattr(node, "end_lineno", None) or node.lineno
        spans.append((_first_line(node), end, node.lineno))
    return spans


def required_line(spans: list[tuple[int, int, int]], line: int) -> int | None:
    best: tuple[int, int] | None = None
    for start, end, required in spans:
        if start <= line <= end and (best is None or end - start < best[0]):
            best = (end - start, required)
    return best[1] if best else None


def class_spans(source: str) -> list[tuple[int, int]]:
    tree = _parse(source)
    if tree is None:
        return []
    return [
        (_first_line(node), node.end_lineno or node.lineno)
        for node in ast.walk(tree)
        if isinstance(node, ast.ClassDef)
    ]


def _strip_docstrings(tree: ast.Module) -> ast.Module:
    for node in ast.walk(tree):
        if isinstance(node, SCOPES) and node.body and _is_string_statement(node.body[0]):
            node.body = node.body[1:] or [ast.Pass()]
    return tree


def normalized_dump(source: str) -> str | None:
    tree = _parse(source)
    if tree is None:
        return None
    return ast.dump(_strip_docstrings(tree))


def same_syntax(base_source: str, head_source: str) -> bool:
    base = normalized_dump(base_source)
    head = normalized_dump(head_source)
    return base is not None and base == head
