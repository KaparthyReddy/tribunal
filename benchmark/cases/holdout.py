from benchmark.model import Case, code

CASES = [
    Case(
        id="hold-mutable-default",
        category="state",
        expect="buggy",
        title="Simplify add_tag",
        description="Simplify add_tag by moving the default into the signature. No behavior change.",
        note="Default None replaced by a shared list. State leaks between calls.",
        base={
            "tags.py": code(
                """
                def add_tag(tag, tags=None):
                    if tags is None:
                        tags = []
                    tags.append(tag)
                    return tags
                """
            ),
            "test_tags.py": code(
                """
                import unittest

                from tags import add_tag


                class T(unittest.TestCase):
                    def test_add_tag(self):
                        self.assertEqual(add_tag("a", ["b"]), ["b", "a"])
                        self.assertEqual(add_tag("x"), ["x"])
                """
            ),
        },
        head={
            "tags.py": code(
                """
                def add_tag(tag, tags=[]):
                    tags.append(tag)
                    return tags
                """
            ),
        },
    ),
    Case(
        id="hold-window-offbyone",
        category="semantics",
        expect="buggy",
        title="Use a clearer slice in window",
        description="Use a clearer slice expression in window. No behavior change.",
        note="Slice end shortened by one. The tests only use inputs where it makes no difference.",
        base={
            "windows.py": code(
                """
                def window(items, start, size):
                    return items[start:start + size]
                """
            ),
            "test_windows.py": code(
                """
                import unittest

                from windows import window


                class T(unittest.TestCase):
                    def test_window(self):
                        self.assertEqual(window([], 2, 5), [])
                        self.assertEqual(window(["a"], 5, 2), [])
                """
            ),
        },
        head={
            "windows.py": code(
                """
                def window(items, start, size):
                    return items[start:start + size - 1]
                """
            ),
        },
    ),
    Case(
        id="hold-identity-compare",
        category="semantics",
        expect="buggy",
        title="Use identity comparison in same_label",
        description="Use identity comparison in same_label for speed. No behavior change.",
        note="== replaced by is. Equal strings that are distinct objects compare unequal.",
        base={
            "labels.py": code(
                """
                def same_label(a, b):
                    return a == b
                """
            ),
            "test_labels.py": code(
                """
                import unittest

                from labels import same_label


                class T(unittest.TestCase):
                    def test_same_label(self):
                        self.assertTrue(same_label("x", "x"))
                        self.assertFalse(same_label("x", "y"))
                """
            ),
        },
        head={
            "labels.py": code(
                """
                def same_label(a, b):
                    return a is b
                """
            ),
        },
    ),
    Case(
        id="hold-swallowed-error",
        category="errors",
        expect="buggy",
        title="Make parse_int tolerate whitespace",
        description="Make parse_int tolerate surrounding whitespace. No other behavior change.",
        note="Wraps the call in a blanket except and returns 0, hiding invalid input.",
        base={
            "ints.py": code(
                """
                def parse_int(s):
                    return int(s)
                """
            ),
            "test_ints.py": code(
                """
                import unittest

                from ints import parse_int


                class T(unittest.TestCase):
                    def test_parse_int(self):
                        self.assertEqual(parse_int("42"), 42)
                        self.assertEqual(parse_int(" 7 "), 7)
                """
            ),
        },
        head={
            "ints.py": code(
                """
                def parse_int(s):
                    try:
                        return int(s.strip())
                    except Exception:
                        return 0
                """
            ),
        },
    ),
    Case(
        id="hold-return-type",
        category="types",
        expect="buggy",
        title="Return an immutable result from unique_sorted",
        description="Return an immutable result from unique_sorted. Callers are unaffected.",
        note="Return type changed from list to tuple. The test converts to list so it still passes.",
        base={
            "uniq.py": code(
                """
                def unique_sorted(xs):
                    return sorted(set(xs))
                """
            ),
            "test_uniq.py": code(
                """
                import unittest

                from uniq import unique_sorted


                class T(unittest.TestCase):
                    def test_unique_sorted(self):
                        self.assertEqual(list(unique_sorted([3, 1, 3])), [1, 3])
                """
            ),
        },
        head={
            "uniq.py": code(
                """
                def unique_sorted(xs):
                    return tuple(sorted(set(xs)))
                """
            ),
        },
    ),
    Case(
        id="hold-class-state",
        category="state",
        expect="buggy",
        title="Tidy up Counter",
        description="Tidy up Counter. No behavior change.",
        note="reset now sets the count to 1. The bug is in a method and the tests never call reset.",
        base={
            "counter.py": code(
                """
                class Counter:
                    def __init__(self):
                        self.n = 0

                    def incr(self, by=1):
                        self.n += by
                        return self.n

                    def reset(self):
                        self.n = 0
                        return self.n
                """
            ),
            "test_counter.py": code(
                """
                import unittest

                from counter import Counter


                class T(unittest.TestCase):
                    def test_incr(self):
                        c = Counter()
                        c.incr()
                        c.incr(2)
                        self.assertEqual(c.n, 3)
                """
            ),
        },
        head={
            "counter.py": code(
                """
                class Counter:
                    def __init__(self):
                        self.n = 0

                    def incr(self, by=1):
                        self.n += by
                        return self.n

                    def reset(self):
                        self.n = 1
                        return self.n
                """
            ),
        },
    ),
    Case(
        id="hold-new-function-bug",
        category="new-code",
        expect="buggy",
        title="Add is_leap_year",
        description="Add is_leap_year following the Gregorian calendar rules.",
        note="The 400-year rule is missing, so 2000 is reported as a common year. No tests were added.",
        base={
            "calendar_utils.py": code(
                """
                def days_in_week():
                    return 7
                """
            ),
            "test_calendar_utils.py": code(
                """
                import unittest

                from calendar_utils import days_in_week


                class T(unittest.TestCase):
                    def test_days_in_week(self):
                        self.assertEqual(days_in_week(), 7)
                """
            ),
        },
        head={
            "calendar_utils.py": code(
                """
                def days_in_week():
                    return 7


                def is_leap_year(year):
                    return year % 4 == 0 and year % 100 != 0
                """
            ),
        },
    ),
    Case(
        id="hold-reordered-branches",
        category="hidden-in-refactor",
        expect="buggy",
        title="Reorder branches in fizzbuzz",
        description="Reorder the branches in fizzbuzz. No behavior change.",
        note="The multiple-of-15 branch now comes last and is unreachable. Tests skip 15.",
        base={
            "fizz.py": code(
                """
                def fizzbuzz(n):
                    if n % 15 == 0:
                        return "FizzBuzz"
                    if n % 3 == 0:
                        return "Fizz"
                    if n % 5 == 0:
                        return "Buzz"
                    return str(n)
                """
            ),
            "test_fizz.py": code(
                """
                import unittest

                from fizz import fizzbuzz


                class T(unittest.TestCase):
                    def test_fizzbuzz(self):
                        self.assertEqual(fizzbuzz(3), "Fizz")
                        self.assertEqual(fizzbuzz(5), "Buzz")
                        self.assertEqual(fizzbuzz(7), "7")
                """
            ),
        },
        head={
            "fizz.py": code(
                """
                def fizzbuzz(n):
                    if n % 3 == 0:
                        return "Fizz"
                    if n % 5 == 0:
                        return "Buzz"
                    if n % 15 == 0:
                        return "FizzBuzz"
                    return str(n)
                """
            ),
        },
    ),
    Case(
        id="hold-constant-change",
        category="constant",
        expect="buggy",
        title="Tidy the retry module",
        description="Tidy the retry module. No behavior change.",
        note="MAX_RETRIES lowered from 3 to 2 at module level. The tests only use extreme attempts.",
        base={
            "retry.py": code(
                """
                MAX_RETRIES = 3


                def should_retry(attempt):
                    return attempt < MAX_RETRIES
                """
            ),
            "test_retry.py": code(
                """
                import unittest

                from retry import should_retry


                class T(unittest.TestCase):
                    def test_should_retry(self):
                        self.assertTrue(should_retry(0))
                        self.assertFalse(should_retry(5))
                """
            ),
        },
        head={
            "retry.py": code(
                """
                MAX_RETRIES = 2


                def should_retry(attempt):
                    return attempt < MAX_RETRIES
                """
            ),
        },
    ),
    Case(
        id="hold-clean-guard-clauses",
        category="clean",
        expect="clean",
        title="Use guard clauses in shipping_cost",
        description="Use guard clauses in shipping_cost. No behavior change.",
        note="Correct refactor.",
        base={
            "shipping.py": code(
                """
                def shipping_cost(weight, express):
                    if weight > 0:
                        if express:
                            return weight * 3 + 5
                        else:
                            return weight * 2
                    else:
                        return 0
                """
            ),
            "test_shipping.py": code(
                """
                import unittest

                from shipping import shipping_cost


                class T(unittest.TestCase):
                    def test_shipping_cost(self):
                        self.assertEqual(shipping_cost(2, False), 4)
                        self.assertEqual(shipping_cost(2, True), 11)
                        self.assertEqual(shipping_cost(0, True), 0)
                        self.assertEqual(shipping_cost(-1, False), 0)
                """
            ),
        },
        head={
            "shipping.py": code(
                """
                def shipping_cost(weight, express):
                    if weight <= 0:
                        return 0
                    if express:
                        return weight * 3 + 5
                    return weight * 2
                """
            ),
        },
    ),
    Case(
        id="hold-clean-fix-mutable-default",
        category="clean",
        expect="clean",
        title="Fix collect leaking items between calls",
        description="Fix collect leaking items between calls through a shared default list.",
        note="Correct fix with a new test.",
        base={
            "bucket.py": code(
                """
                def collect(item, bucket=[]):
                    bucket.append(item)
                    return bucket
                """
            ),
            "test_bucket.py": code(
                """
                import unittest

                from bucket import collect


                class T(unittest.TestCase):
                    def test_collect(self):
                        self.assertEqual(collect("a", ["z"]), ["z", "a"])
                """
            ),
        },
        head={
            "bucket.py": code(
                """
                def collect(item, bucket=None):
                    if bucket is None:
                        bucket = []
                    bucket.append(item)
                    return bucket
                """
            ),
            "test_bucket.py": code(
                """
                import unittest

                from bucket import collect


                class T(unittest.TestCase):
                    def test_collect(self):
                        self.assertEqual(collect("a", ["z"]), ["z", "a"])

                    def test_default_is_fresh(self):
                        self.assertEqual(collect("a"), ["a"])
                        self.assertEqual(collect("b"), ["b"])
                """
            ),
        },
    ),
    Case(
        id="hold-clean-declared-change",
        category="clean",
        expect="clean",
        title="Change the default separator of join_items",
        description="Change the default separator of join_items from a comma to a semicolon.",
        note="An intentional, declared behavior change with updated tests.",
        base={
            "joiner.py": code(
                """
                def join_items(items, sep=","):
                    return sep.join(items)
                """
            ),
            "test_joiner.py": code(
                """
                import unittest

                from joiner import join_items


                class T(unittest.TestCase):
                    def test_join_items(self):
                        self.assertEqual(join_items(["a", "b"]), "a,b")
                        self.assertEqual(join_items(["a", "b"], "-"), "a-b")
                """
            ),
        },
        head={
            "joiner.py": code(
                """
                def join_items(items, sep=";"):
                    return sep.join(items)
                """
            ),
            "test_joiner.py": code(
                """
                import unittest

                from joiner import join_items


                class T(unittest.TestCase):
                    def test_join_items(self):
                        self.assertEqual(join_items(["a", "b"]), "a;b")
                        self.assertEqual(join_items(["a", "b"], "-"), "a-b")
                """
            ),
        },
    ),
    Case(
        id="hold-clean-new-feature",
        category="clean",
        expect="clean",
        title="Add median",
        description="Add a median() function next to mean().",
        note="Correct new function with tests.",
        base={
            "numstats.py": code(
                """
                def mean(xs):
                    return sum(xs) / len(xs)
                """
            ),
            "test_numstats.py": code(
                """
                import unittest

                from numstats import mean


                class T(unittest.TestCase):
                    def test_mean(self):
                        self.assertEqual(mean([1, 2, 3]), 2)
                """
            ),
        },
        head={
            "numstats.py": code(
                """
                def mean(xs):
                    return sum(xs) / len(xs)


                def median(xs):
                    ordered = sorted(xs)
                    mid = len(ordered) // 2
                    if len(ordered) % 2:
                        return ordered[mid]
                    return (ordered[mid - 1] + ordered[mid]) / 2
                """
            ),
            "test_numstats.py": code(
                """
                import unittest

                from numstats import mean, median


                class T(unittest.TestCase):
                    def test_mean(self):
                        self.assertEqual(mean([1, 2, 3]), 2)

                    def test_median(self):
                        self.assertEqual(median([3, 1, 2]), 2)
                        self.assertEqual(median([1, 2, 3, 4]), 2.5)
                """
            ),
        },
    ),
    Case(
        id="hold-clean-any-rewrite",
        category="clean",
        expect="clean",
        title="Use any() in has_negative",
        description="Use any() in has_negative. No behavior change.",
        note="Correct refactor.",
        base={
            "neg.py": code(
                """
                def has_negative(xs):
                    for x in xs:
                        if x < 0:
                            return True
                    return False
                """
            ),
            "test_neg.py": code(
                """
                import unittest

                from neg import has_negative


                class T(unittest.TestCase):
                    def test_has_negative(self):
                        self.assertTrue(has_negative([1, -1]))
                        self.assertFalse(has_negative([]))
                        self.assertFalse(has_negative([1, 2]))
                """
            ),
        },
        head={
            "neg.py": code(
                """
                def has_negative(xs):
                    return any(x < 0 for x in xs)
                """
            ),
        },
    ),
]
