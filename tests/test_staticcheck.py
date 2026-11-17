from tribunal.agents.staticcheck import (
    class_spans,
    normalized_dump,
    required_line,
    same_syntax,
    statement_spans,
)

SIMPLE = "def f(a):\n    x = a + 1\n    if x > 2:\n        return x\n    return 0\n"
MULTI = "def g():\n    return foo(\n        1,\n        2,\n    )\n"
DOCSTRING = 'def h():\n    """doc"""\n    return 1\n'


def test_each_statement_line_requires_itself() -> None:
    spans = statement_spans(SIMPLE)
    assert spans is not None
    assert [required_line(spans, line) for line in range(1, 6)] == [1, 2, 3, 4, 5]


def test_continuation_lines_map_to_the_statement_start() -> None:
    spans = statement_spans(MULTI)
    assert spans is not None
    assert required_line(spans, 4) == 2
    assert required_line(spans, 5) == 2


def test_docstring_lines_are_not_required() -> None:
    spans = statement_spans(DOCSTRING)
    assert spans is not None
    assert required_line(spans, 2) == 1
    assert required_line(spans, 3) == 3


def test_annotation_without_value_is_ignored() -> None:
    spans = statement_spans("x: int\ny = 1\n")
    assert spans is not None
    assert [required for _, _, required in spans] == [2]


def test_invalid_source_is_rejected() -> None:
    assert statement_spans("def (") is None
    assert class_spans("def (") == []
    assert normalized_dump("def (") is None
    assert not same_syntax("def (", "x = 1\n")


def test_class_spans() -> None:
    assert class_spans("class A:\n    x = 1\n\n\nclass B:\n    pass\n") == [(1, 2), (5, 6)]


def test_comments_formatting_and_docstrings_do_not_change_syntax() -> None:
    base = "def f(a):\n    return a+1\n"
    assert same_syntax(base, "def f(a):\n    # note\n    return a + 1  # tail\n")
    assert same_syntax(base, 'def f(a):\n    """Return a plus one."""\n    return a + 1\n')
    assert same_syntax('def f():\n    """only a docstring"""\n', "def f():\n    pass\n")


def test_real_changes_are_detected() -> None:
    assert not same_syntax("def f(a):\n    return a + 1\n", "def f(a):\n    return a + 2\n")
    assert not same_syntax("def f(a=1):\n    return a\n", "def f(a=2):\n    return a\n")
