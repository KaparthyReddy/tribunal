from benchmark.model import Case, code

CASES = [
    Case(
        id="claim-false-fix",
        category="false-claim",
        expect="buggy",
        title="Fix crash on empty list in maximum",
        description="Fixes the crash when maximum() is called with an empty list.",
        note="Only variables were renamed. maximum([]) still raises IndexError.",
        base={
            "agg.py": code(
                """
                def maximum(xs):
                    best = xs[0]
                    for x in xs:
                        if x > best:
                            best = x
                    return best
                """
            ),
            "test_agg.py": code(
                """
                import unittest

                from agg import maximum


                class T(unittest.TestCase):
                    def test_maximum(self):
                        self.assertEqual(maximum([1, 3, 2]), 3)
                """
            ),
        },
        head={
            "agg.py": code(
                """
                def maximum(values):
                    best = values[0]
                    for v in values:
                        if v > best:
                            best = v
                    return best
                """
            ),
        },
    ),
    Case(
        id="claim-false-no-change",
        category="false-claim",
        expect="buggy",
        title="Reformat greet",
        description="Reformat greet. No behavior change.",
        note="Default punctuation changed from ! to . while tests pass it explicitly.",
        base={
            "greet.py": code(
                """
                def greet(name, punct="!"):
                    return "Hello, " + name + punct
                """
            ),
            "test_greet.py": code(
                """
                import unittest

                from greet import greet


                class T(unittest.TestCase):
                    def test_greet(self):
                        self.assertEqual(greet("Ann", "?"), "Hello, Ann?")
                """
            ),
        },
        head={
            "greet.py": code(
                """
                def greet(name, punct="."):
                    return "Hello, " + name + punct
                """
            ),
        },
    ),
]
