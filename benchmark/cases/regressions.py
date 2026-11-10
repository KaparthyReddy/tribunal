from benchmark.model import Case, code

CASES = [
    Case(
        id="regress-last-n",
        category="regression",
        expect="buggy",
        title="Tidy up last_n",
        description="Tidy up last_n. No behavior change.",
        note="Start index shifted by one. Existing tests fail.",
        tests_catch=True,
        base={
            "seq.py": code(
                '''
                def last_n(items, n):
                    start = len(items) - n
                    return items[start:]
                '''
            ),
            "test_seq.py": code(
                '''
                import unittest

                from seq import last_n


                class T(unittest.TestCase):
                    def test_last_n(self):
                        self.assertEqual(last_n([1, 2, 3, 4], 2), [3, 4])
                        self.assertEqual(last_n([1, 2, 3], 3), [1, 2, 3])
                '''
            ),
        },
        head={
            "seq.py": code(
                '''
                def last_n(items, n):
                    start = len(items) - n + 1
                    return items[start:]
                '''
            ),
        },
    ),
    Case(
        id="regress-is-adult",
        category="regression",
        expect="buggy",
        title="Cleanup in is_adult",
        description="Cleanup in is_adult. No behavior change.",
        note="Boundary changed from >= to >. Existing tests fail at 18.",
        tests_catch=True,
        base={
            "age.py": code(
                '''
                def is_adult(age):
                    return age >= 18
                '''
            ),
            "test_age.py": code(
                '''
                import unittest

                from age import is_adult


                class T(unittest.TestCase):
                    def test_is_adult(self):
                        self.assertTrue(is_adult(30))
                        self.assertFalse(is_adult(10))
                        self.assertTrue(is_adult(18))
                '''
            ),
        },
        head={
            "age.py": code(
                '''
                def is_adult(age):
                    return age > 18
                '''
            ),
        },
    ),
    Case(
        id="regress-normalize",
        category="regression",
        expect="buggy",
        title="Speed up normalize",
        description="Speed up normalize by skipping a redundant step.",
        note="strip() removed. Existing tests fail on padded input.",
        tests_catch=True,
        base={
            "text.py": code(
                '''
                def normalize(s):
                    return s.strip().lower()
                '''
            ),
            "test_text.py": code(
                '''
                import unittest

                from text import normalize


                class T(unittest.TestCase):
                    def test_normalize(self):
                        self.assertEqual(normalize("  Hi "), "hi")
                '''
            ),
        },
        head={
            "text.py": code(
                '''
                def normalize(s):
                    return s.lower()
                '''
            ),
        },
    ),
    Case(
        id="regress-clamp",
        category="regression",
        expect="buggy",
        title="Reorder clamp expression",
        description="Reorder the clamp expression for readability. No behavior change.",
        note="min and max swapped. Existing tests fail.",
        tests_catch=True,
        base={
            "bounds.py": code(
                '''
                def clamp(x, lo=0, hi=10):
                    return max(lo, min(x, hi))
                '''
            ),
            "test_bounds.py": code(
                '''
                import unittest

                from bounds import clamp


                class T(unittest.TestCase):
                    def test_clamp(self):
                        self.assertEqual(clamp(5), 5)
                        self.assertEqual(clamp(-3), 0)
                        self.assertEqual(clamp(99), 10)
                '''
            ),
        },
        head={
            "bounds.py": code(
                '''
                def clamp(x, lo=0, hi=10):
                    return min(lo, max(x, hi))
                '''
            ),
        },
    ),
    Case(
        id="regress-ratio",
        category="regression",
        expect="buggy",
        title="Normalize operand order in ratio",
        description="Normalize operand order in ratio. No behavior change.",
        note="Operands swapped. Existing tests fail.",
        tests_catch=True,
        base={
            "ratio.py": code(
                '''
                def ratio(a, b):
                    return a / b
                '''
            ),
            "test_ratio.py": code(
                '''
                import unittest

                from ratio import ratio


                class T(unittest.TestCase):
                    def test_ratio(self):
                        self.assertEqual(ratio(4, 2), 2)
                '''
            ),
        },
        head={
            "ratio.py": code(
                '''
                def ratio(a, b):
                    return b / a
                '''
            ),
        },
    ),
]
