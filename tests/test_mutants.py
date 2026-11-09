from tribunal.agents import generate_mutants

SOURCE = "def f(a, b):\n    if a == b:\n        return True\n    return a + 1\n"


def test_generates_expected_operators() -> None:
    mutants = generate_mutants(SOURCE, "m.py", [(1, 4)], limit=50)
    descriptions = {m.description for m in mutants}
    assert {"Eq -> NotEq", "True -> False", "return value -> None", "Add -> Sub", "1 -> 2"} <= (
        descriptions
    )
    for mutant in mutants:
        compile(mutant.source, "m.py", "exec")
        assert mutant.file == "m.py"


def test_respects_changed_spans() -> None:
    mutants = generate_mutants(SOURCE, "m.py", [(4, 4)], limit=50)
    descriptions = {m.description for m in mutants}
    assert descriptions == {"return value -> None", "Add -> Sub", "1 -> 2"}
    assert {m.line for m in mutants} == {4}


def test_limit_is_enforced() -> None:
    assert len(generate_mutants(SOURCE, "m.py", [(1, 4)], limit=2)) == 2


def test_invalid_source_returns_empty() -> None:
    assert generate_mutants("def (", "m.py", [(1, 1)]) == []


def test_mutants_change_behavior() -> None:
    mutants = generate_mutants("def f(a):\n    return a + 1\n", "m.py", [(2, 2)], limit=10)
    by_description = {m.description: m for m in mutants}
    namespace: dict = {}
    exec(by_description["Add -> Sub"].source, namespace)
    assert namespace["f"](5) == 4
    namespace = {}
    exec(by_description["return value -> None"].source, namespace)
    assert namespace["f"](5) is None
