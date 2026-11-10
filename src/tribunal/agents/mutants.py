import ast
from collections.abc import Callable
from dataclasses import dataclass

type Mutation = tuple[str, Callable[[], None]]

_CMP: dict[type, type] = {
    ast.Eq: ast.NotEq,
    ast.NotEq: ast.Eq,
    ast.Lt: ast.GtE,
    ast.LtE: ast.Gt,
    ast.Gt: ast.LtE,
    ast.GtE: ast.Lt,
    ast.Is: ast.IsNot,
    ast.IsNot: ast.Is,
    ast.In: ast.NotIn,
    ast.NotIn: ast.In,
}
_ARITH: dict[type, type] = {ast.Add: ast.Sub, ast.Sub: ast.Add}


@dataclass(frozen=True)
class Mutant:
    file: str
    line: int
    description: str
    source: str


def spread[T](items: list[T], limit: int) -> list[T]:
    if len(items) <= limit:
        return items
    step = len(items) / limit
    return [items[int(i * step)] for i in range(limit)]


def _mutation(node: ast.AST) -> Mutation | None:
    if isinstance(node, ast.Compare):
        old = type(node.ops[0])
        new = _CMP.get(old)
        if new is not None:
            return (
                f"{old.__name__} -> {new.__name__}",
                lambda: node.ops.__setitem__(0, new()),
            )
    if isinstance(node, ast.BinOp | ast.AugAssign):
        old = type(node.op)
        new = _ARITH.get(old)
        if new is not None:
            return (
                f"{old.__name__} -> {new.__name__}",
                lambda: setattr(node, "op", new()),
            )
    if isinstance(node, ast.BoolOp):
        replacement = ast.Or if isinstance(node.op, ast.And) else ast.And
        return (
            f"{type(node.op).__name__} -> {replacement.__name__}",
            lambda: setattr(node, "op", replacement()),
        )
    if isinstance(node, ast.Constant):
        value = node.value
        if isinstance(value, bool):
            return f"{value} -> {not value}", lambda: setattr(node, "value", not value)
        if isinstance(value, int):
            return f"{value} -> {value + 1}", lambda: setattr(node, "value", value + 1)
    if (
        isinstance(node, ast.Return)
        and node.value is not None
        and not (isinstance(node.value, ast.Constant) and node.value.value is None)
    ):
        return "return value -> None", lambda: setattr(node, "value", ast.Constant(value=None))
    return None


def generate_mutants(
    source: str,
    file: str,
    spans: list[tuple[int, int]],
    limit: int = 8,
) -> list[Mutant]:
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError):
        return []

    original = ast.unparse(tree)
    candidates: list[tuple[int, int, str]] = []
    for index, node in enumerate(ast.walk(tree)):
        lineno = getattr(node, "lineno", None)
        if lineno is None or not any(start <= lineno <= end for start, end in spans):
            continue
        mutation = _mutation(node)
        if mutation is not None:
            candidates.append((index, lineno, mutation[0]))

    mutants: list[Mutant] = []
    for index, lineno, description in spread(candidates, limit):
        fresh = ast.parse(source)
        target = list(ast.walk(fresh))[index]
        mutation = _mutation(target)
        if mutation is None:
            continue
        mutation[1]()
        try:
            mutated = ast.unparse(fresh)
        except (ValueError, RecursionError):
            continue
        if mutated == original:
            continue
        mutants.append(
            Mutant(file=file, line=lineno, description=description, source=mutated + "\n")
        )
    return mutants
