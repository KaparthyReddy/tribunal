from benchmark.model import Case, code

CASES = [
    Case(
        id="clean-rename",
        category="clean",
        expect="clean",
        title="Rename locals in total",
        description="Rename locals in total for clarity. No behavior change.",
        note="Correct change.",
        base={
            "calc.py": code(
                """
                def total(xs):
                    t = 0
                    for x in xs:
                        t += x
                    return t
                """
            ),
            "test_calc.py": code(
                """
                import unittest

                from calc import total


                class T(unittest.TestCase):
                    def test_total(self):
                        self.assertEqual(total([1, 2, 3]), 6)
                        self.assertEqual(total([]), 0)
                """
            ),
        },
        head={
            "calc.py": code(
                """
                def total(xs):
                    result = 0
                    for x in xs:
                        result += x
                    return result
                """
            ),
        },
    ),
    Case(
        id="clean-comprehension",
        category="clean",
        expect="clean",
        title="Use a comprehension in squares",
        description="Use a list comprehension in squares. No behavior change.",
        note="Correct change.",
        base={
            "squares.py": code(
                """
                def squares(xs):
                    out = []
                    for x in xs:
                        out.append(x * x)
                    return out
                """
            ),
            "test_squares.py": code(
                """
                import unittest

                from squares import squares


                class T(unittest.TestCase):
                    def test_squares(self):
                        self.assertEqual(squares([1, 2, 3]), [1, 4, 9])
                        self.assertEqual(squares([]), [])
                """
            ),
        },
        head={
            "squares.py": code(
                """
                def squares(xs):
                    return [x * x for x in xs]
                """
            ),
        },
    ),
    Case(
        id="clean-real-fix",
        category="clean",
        expect="clean",
        title="Fix ZeroDivisionError in safe_div",
        description=(
            "Fixes ZeroDivisionError in safe_div by returning None when the divisor is zero."
        ),
        note="Correct fix with a new test.",
        base={
            "safe.py": code(
                """
                def safe_div(a, b):
                    return a / b
                """
            ),
            "test_safe.py": code(
                """
                import unittest

                from safe import safe_div


                class T(unittest.TestCase):
                    def test_safe_div(self):
                        self.assertEqual(safe_div(6, 3), 2)
                """
            ),
        },
        head={
            "safe.py": code(
                """
                def safe_div(a, b):
                    if b == 0:
                        return None
                    return a / b
                """
            ),
            "test_safe.py": code(
                """
                import unittest

                from safe import safe_div


                class T(unittest.TestCase):
                    def test_safe_div(self):
                        self.assertEqual(safe_div(6, 3), 2)

                    def test_zero_divisor(self):
                        self.assertIsNone(safe_div(1, 0))
                """
            ),
        },
    ),
    Case(
        id="clean-docstring",
        category="clean",
        expect="clean",
        title="Add a docstring to area",
        description="Add a docstring to area.",
        note="Documentation only.",
        base={
            "area.py": code(
                """
                def area(w, h):
                    return w * h
                """
            ),
            "test_area.py": code(
                """
                import unittest

                from area import area


                class T(unittest.TestCase):
                    def test_area(self):
                        self.assertEqual(area(2, 3), 6)
                """
            ),
        },
        head={
            "area.py": code(
                '''
                def area(w, h):
                    """Return the area of a w by h rectangle."""
                    return w * h
                '''
            ),
        },
    ),
    Case(
        id="clean-new-function",
        category="clean",
        expect="clean",
        title="Add triple",
        description="Add a triple() helper next to double().",
        note="New function with its own test.",
        base={
            "mathx.py": code(
                """
                def double(x):
                    return x * 2
                """
            ),
            "test_mathx.py": code(
                """
                import unittest

                from mathx import double


                class T(unittest.TestCase):
                    def test_double(self):
                        self.assertEqual(double(4), 8)
                """
            ),
        },
        head={
            "mathx.py": code(
                """
                def double(x):
                    return x * 2


                def triple(x):
                    return x * 3
                """
            ),
            "test_mathx.py": code(
                """
                import unittest

                from mathx import double, triple


                class T(unittest.TestCase):
                    def test_double(self):
                        self.assertEqual(double(4), 8)

                    def test_triple(self):
                        self.assertEqual(triple(2), 6)
                """
            ),
        },
    ),
    Case(
        id="clean-constant",
        category="clean",
        expect="clean",
        title="Extract the tax rate",
        description="Extract the tax rate into a constant.",
        note="Correct change.",
        base={
            "pricing.py": code(
                """
                def with_tax(price):
                    return price * 1.08
                """
            ),
            "test_pricing.py": code(
                """
                import unittest

                from pricing import with_tax


                class T(unittest.TestCase):
                    def test_with_tax(self):
                        self.assertAlmostEqual(with_tax(100), 108.0)
                """
            ),
        },
        head={
            "pricing.py": code(
                """
                TAX_RATE = 1.08


                def with_tax(price):
                    return price * TAX_RATE
                """
            ),
        },
    ),
    Case(
        id="clean-early-return",
        category="clean",
        expect="clean",
        title="Use early returns in sign",
        description="Use early returns in sign. No behavior change.",
        note="Correct change.",
        base={
            "sign.py": code(
                """
                def sign(x):
                    if x > 0:
                        result = 1
                    elif x < 0:
                        result = -1
                    else:
                        result = 0
                    return result
                """
            ),
            "test_sign.py": code(
                """
                import unittest

                from sign import sign


                class T(unittest.TestCase):
                    def test_sign(self):
                        self.assertEqual(sign(5), 1)
                        self.assertEqual(sign(1), 1)
                        self.assertEqual(sign(-3), -1)
                        self.assertEqual(sign(-1), -1)
                        self.assertEqual(sign(0), 0)
                """
            ),
        },
        head={
            "sign.py": code(
                """
                def sign(x):
                    if x > 0:
                        return 1
                    if x < 0:
                        return -1
                    return 0
                """
            ),
        },
    ),
]
