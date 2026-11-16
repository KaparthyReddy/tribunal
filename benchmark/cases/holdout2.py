from benchmark.model import Case, code

CASES = [
    Case(
        id="h2-dict-get",
        category="semantics",
        expect="buggy",
        title="Use dict.get in config_value",
        description="Use dict.get in config_value for clarity. No behavior change.",
        note="A missing key now returns None instead of raising KeyError. Tests only use present keys.",
        base={
            "config.py": code(
                """
                def config_value(config, key):
                    return config[key]
                """
            ),
            "test_config.py": code(
                """
                import unittest

                from config import config_value


                class T(unittest.TestCase):
                    def test_config_value(self):
                        self.assertEqual(config_value({"a": 1}, "a"), 1)
                """
            ),
        },
        head={
            "config.py": code(
                """
                def config_value(config, key):
                    return config.get(key)
                """
            ),
        },
    ),
    Case(
        id="h2-default-arg",
        category="semantics",
        expect="buggy",
        title="Tidy paginate",
        description="Tidy the paginate signature. No behavior change.",
        note="The default page size doubled. Tests always pass the size explicitly.",
        base={
            "paging.py": code(
                """
                def paginate(items, page, size=10):
                    start = page * size
                    return items[start:start + size]
                """
            ),
            "test_paging.py": code(
                """
                import unittest

                from paging import paginate


                class T(unittest.TestCase):
                    def test_paginate(self):
                        self.assertEqual(paginate(list(range(30)), 1, 10), list(range(10, 20)))
                        self.assertEqual(paginate(list(range(30)), 0, 5), [0, 1, 2, 3, 4])
                """
            ),
        },
        head={
            "paging.py": code(
                """
                def paginate(items, page, size=20):
                    start = page * size
                    return items[start:start + size]
                """
            ),
        },
    ),
    Case(
        id="h2-sort-tiebreak",
        category="semantics",
        expect="buggy",
        title="Make sort_by_length deterministic",
        description="Make the ordering of sort_by_length deterministic. No behavior change.",
        note="Ties are now ordered alphabetically instead of keeping input order. Tests have no ties.",
        base={
            "sorting.py": code(
                """
                def sort_by_length(words):
                    return sorted(words, key=len)
                """
            ),
            "test_sorting.py": code(
                """
                import unittest

                from sorting import sort_by_length


                class T(unittest.TestCase):
                    def test_sort_by_length(self):
                        self.assertEqual(sort_by_length(["ccc", "a", "bb"]), ["a", "bb", "ccc"])
                """
            ),
        },
        head={
            "sorting.py": code(
                """
                def sort_by_length(words):
                    return sorted(words, key=lambda w: (len(w), w))
                """
            ),
        },
    ),
    Case(
        id="h2-int-division",
        category="semantics",
        expect="buggy",
        title="Avoid float noise in average",
        description="Use integer division in average to avoid floating point noise. No behavior change.",
        note="Floor division truncates fractional averages. Tests only use evenly divisible inputs.",
        base={
            "averages.py": code(
                """
                def average(xs):
                    return sum(xs) / len(xs)
                """
            ),
            "test_averages.py": code(
                """
                import unittest

                from averages import average


                class T(unittest.TestCase):
                    def test_average(self):
                        self.assertEqual(average([2, 4, 6]), 4)
                        self.assertEqual(average([5]), 5)
                """
            ),
        },
        head={
            "averages.py": code(
                """
                def average(xs):
                    return sum(xs) // len(xs)
                """
            ),
        },
    ),
    Case(
        id="h2-method-overdraft",
        category="state",
        expect="buggy",
        title="Simplify Account.withdraw",
        description="Simplify Account.withdraw. No behavior change.",
        note="The insufficient funds check was removed from a method. Tests never overdraw.",
        base={
            "account.py": code(
                """
                class Account:
                    def __init__(self, balance=0):
                        self.balance = balance

                    def deposit(self, amount):
                        self.balance += amount
                        return self.balance

                    def withdraw(self, amount):
                        if amount > self.balance:
                            raise ValueError("insufficient funds")
                        self.balance -= amount
                        return self.balance
                """
            ),
            "test_account.py": code(
                """
                import unittest

                from account import Account


                class T(unittest.TestCase):
                    def test_deposit(self):
                        self.assertEqual(Account(100).deposit(50), 150)

                    def test_withdraw(self):
                        self.assertEqual(Account(100).withdraw(30), 70)
                """
            ),
        },
        head={
            "account.py": code(
                """
                class Account:
                    def __init__(self, balance=0):
                        self.balance = balance

                    def deposit(self, amount):
                        self.balance += amount
                        return self.balance

                    def withdraw(self, amount):
                        self.balance -= amount
                        return self.balance
                """
            ),
        },
    ),
    Case(
        id="h2-truncate-boundary",
        category="boundary",
        expect="buggy",
        title="Tidy truncate",
        description="Tidy the length check in truncate. No behavior change.",
        note="A string exactly n long is now truncated. Tests never use that length.",
        base={
            "trunc.py": code(
                """
                def truncate(s, n):
                    if len(s) <= n:
                        return s
                    return s[: n - 3] + "..."
                """
            ),
            "test_trunc.py": code(
                """
                import unittest

                from trunc import truncate


                class T(unittest.TestCase):
                    def test_truncate(self):
                        self.assertEqual(truncate("hi", 10), "hi")
                        self.assertEqual(truncate("hello world", 8), "hello...")
                """
            ),
        },
        head={
            "trunc.py": code(
                """
                def truncate(s, n):
                    if len(s) < n:
                        return s
                    return s[: n - 3] + "..."
                """
            ),
        },
    ),
    Case(
        id="h2-regex-anchor",
        category="semantics",
        expect="buggy",
        title="Simplify is_hex",
        description="Simplify is_hex. No behavior change.",
        note="fullmatch became match, so strings with a valid prefix are accepted.",
        base={
            "hexcheck.py": code(
                """
                import re


                def is_hex(s):
                    return re.fullmatch(r"[0-9a-f]+", s) is not None
                """
            ),
            "test_hexcheck.py": code(
                """
                import unittest

                from hexcheck import is_hex


                class T(unittest.TestCase):
                    def test_is_hex(self):
                        self.assertTrue(is_hex("deadbeef"))
                        self.assertFalse(is_hex("xyz"))
                """
            ),
        },
        head={
            "hexcheck.py": code(
                """
                import re


                def is_hex(s):
                    return re.match(r"[0-9a-f]+", s) is not None
                """
            ),
        },
    ),
    Case(
        id="h2-new-word-count",
        category="new-code",
        expect="buggy",
        title="Add word_count",
        description="Add word_count, which returns the number of words in a text.",
        note="Splitting on a single space counts empty tokens for repeated spaces. No tests were added.",
        base={
            "text_utils.py": code(
                """
                def shout(s):
                    return s.upper()
                """
            ),
            "test_text_utils.py": code(
                """
                import unittest

                from text_utils import shout


                class T(unittest.TestCase):
                    def test_shout(self):
                        self.assertEqual(shout("hi"), "HI")
                """
            ),
        },
        head={
            "text_utils.py": code(
                """
                def shout(s):
                    return s.upper()


                def word_count(text):
                    return len(text.split(" "))
                """
            ),
        },
    ),
    Case(
        id="h2-label-boundary",
        category="boundary",
        expect="buggy",
        title="Tidy shipping_label",
        description="Tidy shipping_label. No behavior change.",
        note="A weight of exactly 10 moved from light to heavy. Every line is exercised by typical inputs.",
        base={
            "shipping.py": code(
                """
                def shipping_label(weight):
                    if weight > 100:
                        return "freight"
                    if weight > 10:
                        return "heavy"
                    return "light"
                """
            ),
            "test_shipping.py": code(
                """
                import unittest

                from shipping import shipping_label


                class T(unittest.TestCase):
                    def test_shipping_label(self):
                        self.assertEqual(shipping_label(500), "freight")
                        self.assertEqual(shipping_label(50), "heavy")
                        self.assertEqual(shipping_label(5), "light")
                """
            ),
        },
        head={
            "shipping.py": code(
                """
                def shipping_label(weight):
                    if weight > 100:
                        return "freight"
                    if weight >= 10:
                        return "heavy"
                    return "light"
                """
            ),
        },
    ),
    Case(
        id="h2-mutates-argument",
        category="state",
        expect="buggy",
        title="Avoid an allocation in sorted_copy",
        description="Avoid allocating a new list in sorted_copy. No behavior change.",
        note="The function now sorts its argument in place. The returned values are identical.",
        base={
            "copies.py": code(
                """
                def sorted_copy(xs):
                    return sorted(xs)
                """
            ),
            "test_copies.py": code(
                """
                import unittest

                from copies import sorted_copy


                class T(unittest.TestCase):
                    def test_sorted_copy(self):
                        self.assertEqual(sorted_copy([3, 1, 2]), [1, 2, 3])
                """
            ),
        },
        head={
            "copies.py": code(
                """
                def sorted_copy(xs):
                    xs.sort()
                    return xs
                """
            ),
        },
    ),
    Case(
        id="h2-tests-catch-it",
        category="regression",
        expect="buggy",
        title="Simplify discount",
        description="Simplify discount. No behavior change.",
        note="The percentage is applied the wrong way round. Existing tests fail.",
        tests_catch=True,
        base={
            "pricing.py": code(
                """
                def discount(price, pct):
                    return price * (100 - pct) / 100
                """
            ),
            "test_pricing.py": code(
                """
                import unittest

                from pricing import discount


                class T(unittest.TestCase):
                    def test_discount(self):
                        self.assertEqual(discount(200, 10), 180)
                """
            ),
        },
        head={
            "pricing.py": code(
                """
                def discount(price, pct):
                    return price * pct / 100
                """
            ),
        },
    ),
    Case(
        id="h2-clean-first-even",
        category="clean",
        expect="clean",
        title="Use next() in first_even",
        description="Use next() in first_even. No behavior change.",
        note="Correct refactor with thin tests.",
        base={
            "evens.py": code(
                """
                def first_even(xs):
                    found = None
                    for x in xs:
                        if x % 2 == 0:
                            found = x
                            break
                    return found
                """
            ),
            "test_evens.py": code(
                """
                import unittest

                from evens import first_even


                class T(unittest.TestCase):
                    def test_first_even(self):
                        self.assertEqual(first_even([1, 2, 3, 4]), 2)
                        self.assertIsNone(first_even([1, 3]))
                """
            ),
        },
        head={
            "evens.py": code(
                """
                def first_even(xs):
                    return next((x for x in xs if x % 2 == 0), None)
                """
            ),
        },
    ),
    Case(
        id="h2-clean-palindrome-fix",
        category="clean",
        expect="clean",
        title="Fix is_palindrome for mixed case",
        description="Fixes is_palindrome returning False for mixed-case palindromes such as Aba.",
        note="Correct fix with a new test that fails on the base commit.",
        base={
            "palindrome.py": code(
                """
                def is_palindrome(s):
                    return s == s[::-1]
                """
            ),
            "test_palindrome.py": code(
                """
                import unittest

                from palindrome import is_palindrome


                class T(unittest.TestCase):
                    def test_is_palindrome(self):
                        self.assertTrue(is_palindrome("abba"))
                        self.assertFalse(is_palindrome("abc"))
                """
            ),
        },
        head={
            "palindrome.py": code(
                """
                def is_palindrome(s):
                    lowered = s.lower()
                    return lowered == lowered[::-1]
                """
            ),
            "test_palindrome.py": code(
                """
                import unittest

                from palindrome import is_palindrome


                class T(unittest.TestCase):
                    def test_is_palindrome(self):
                        self.assertTrue(is_palindrome("abba"))
                        self.assertFalse(is_palindrome("abc"))

                    def test_mixed_case(self):
                        self.assertTrue(is_palindrome("Aba"))
                """
            ),
        },
    ),
    Case(
        id="h2-clean-declared-change",
        category="clean",
        expect="clean",
        title="Shorten the greeting",
        description="Change the greeting from Hello to Hi.",
        note="An intentional, declared behavior change with updated tests.",
        base={
            "greet.py": code(
                """
                def greeting(name):
                    return "Hello, " + name
                """
            ),
            "test_greet.py": code(
                """
                import unittest

                from greet import greeting


                class T(unittest.TestCase):
                    def test_greeting(self):
                        self.assertEqual(greeting("Ann"), "Hello, Ann")
                """
            ),
        },
        head={
            "greet.py": code(
                """
                def greeting(name):
                    return "Hi, " + name
                """
            ),
            "test_greet.py": code(
                """
                import unittest

                from greet import greeting


                class T(unittest.TestCase):
                    def test_greeting(self):
                        self.assertEqual(greeting("Ann"), "Hi, Ann")
                """
            ),
        },
    ),
    Case(
        id="h2-clean-optional-param",
        category="clean",
        expect="clean",
        title="Add an upper option to label",
        description="Add an optional upper parameter to label. Existing calls are unchanged.",
        note="Correct change that adds an optional parameter with a test.",
        base={
            "labels.py": code(
                """
                def label(name):
                    return name.strip()
                """
            ),
            "test_labels.py": code(
                """
                import unittest

                from labels import label


                class T(unittest.TestCase):
                    def test_label(self):
                        self.assertEqual(label(" a "), "a")
                """
            ),
        },
        head={
            "labels.py": code(
                """
                def label(name, upper=False):
                    cleaned = name.strip()
                    if upper:
                        return cleaned.upper()
                    return cleaned
                """
            ),
            "test_labels.py": code(
                """
                import unittest

                from labels import label


                class T(unittest.TestCase):
                    def test_label(self):
                        self.assertEqual(label(" a "), "a")

                    def test_upper(self):
                        self.assertEqual(label(" a ", upper=True), "A")
                """
            ),
        },
    ),
    Case(
        id="h2-clean-dead-code",
        category="clean",
        expect="clean",
        title="Remove unused helper",
        description="Remove the unused _legacy_total helper. No behavior change.",
        note="Correct deletion of a function nothing calls.",
        base={
            "totals.py": code(
                """
                def total(xs):
                    return sum(xs)


                def _legacy_total(xs):
                    t = 0
                    for x in xs:
                        t += x
                    return t
                """
            ),
            "test_totals.py": code(
                """
                import unittest

                from totals import total


                class T(unittest.TestCase):
                    def test_total(self):
                        self.assertEqual(total([1, 2]), 3)
                """
            ),
        },
        head={
            "totals.py": code(
                """
                def total(xs):
                    return sum(xs)
                """
            ),
        },
    ),
    Case(
        id="h2-clean-comment-only",
        category="clean",
        expect="clean",
        title="Add a comment to area",
        description="Add a comment to area. No behavior change.",
        note="Comment only.",
        base={
            "areas.py": code(
                """
                def area(w, h):
                    return w * h
                """
            ),
            "test_areas.py": code(
                """
                import unittest

                from areas import area


                class T(unittest.TestCase):
                    def test_area(self):
                        self.assertEqual(area(2, 3), 6)
                """
            ),
        },
        head={
            "areas.py": code(
                """
                def area(w, h):
                    # width times height
                    return w * h
                """
            ),
        },
    ),
]
