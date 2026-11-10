from benchmark.model import Case, code

CASES = [
    Case(
        id="untested-first-word",
        category="untested",
        expect="buggy",
        title="Simplify first_word",
        description="Simplify first_word. No behavior change.",
        note="Empty-string guard removed. Raises IndexError on empty input. Tests miss it.",
        base={
            "words.py": code(
                '''
                def first_word(s):
                    parts = s.split()
                    if not parts:
                        return ""
                    return parts[0]
                '''
            ),
            "test_words.py": code(
                '''
                import unittest

                from words import first_word


                class T(unittest.TestCase):
                    def test_first_word(self):
                        self.assertEqual(first_word("hello world"), "hello")
                '''
            ),
        },
        head={
            "words.py": code(
                '''
                def first_word(s):
                    return s.split()[0]
                '''
            ),
        },
    ),
    Case(
        id="untested-chunk",
        category="untested",
        expect="buggy",
        title="Rewrite chunk as an explicit loop",
        description="Rewrite chunk as an explicit loop. No behavior change.",
        note="Drops the final partial chunk. Tests only use exact multiples.",
        base={
            "chunks.py": code(
                '''
                def chunk(items, size):
                    return [items[i:i + size] for i in range(0, len(items), size)]
                '''
            ),
            "test_chunks.py": code(
                '''
                import unittest

                from chunks import chunk


                class T(unittest.TestCase):
                    def test_chunk(self):
                        self.assertEqual(chunk([1, 2, 3, 4], 2), [[1, 2], [3, 4]])
                        self.assertEqual(chunk([], 3), [])
                '''
            ),
        },
        head={
            "chunks.py": code(
                '''
                def chunk(items, size):
                    out = []
                    for i in range(0, len(items) - size + 1, size):
                        out.append(items[i:i + size])
                    return out
                '''
            ),
        },
    ),
    Case(
        id="untested-dedupe",
        category="untested",
        expect="buggy",
        title="Simplify dedupe",
        description="Simplify dedupe. No behavior change.",
        note="list(set(...)) loses first-seen order. Tests use already sorted input.",
        base={
            "dedupe.py": code(
                '''
                def dedupe(items):
                    seen = set()
                    out = []
                    for item in items:
                        if item not in seen:
                            seen.add(item)
                            out.append(item)
                    return out
                '''
            ),
            "test_dedupe.py": code(
                '''
                import unittest

                from dedupe import dedupe


                class T(unittest.TestCase):
                    def test_dedupe(self):
                        self.assertEqual(dedupe([1, 1, 2]), [1, 2])
                        self.assertEqual(dedupe([]), [])
                '''
            ),
        },
        head={
            "dedupe.py": code(
                '''
                def dedupe(items):
                    return list(set(items))
                '''
            ),
        },
    ),
    Case(
        id="untested-percent",
        category="untested",
        expect="buggy",
        title="Simplify percent",
        description="Simplify percent. No behavior change.",
        note="Zero-division guard removed. Tests never pass a zero denominator.",
        base={
            "stats.py": code(
                '''
                def percent(part, whole):
                    if whole == 0:
                        return 0
                    return part / whole * 100
                '''
            ),
            "test_stats.py": code(
                '''
                import unittest

                from stats import percent


                class T(unittest.TestCase):
                    def test_percent(self):
                        self.assertEqual(percent(1, 4), 25)
                '''
            ),
        },
        head={
            "stats.py": code(
                '''
                def percent(part, whole):
                    return part / whole * 100
                '''
            ),
        },
    ),
    Case(
        id="untested-parse-bool",
        category="untested",
        expect="buggy",
        title="Drop redundant strip in parse_bool",
        description="Drop the redundant strip in parse_bool. No behavior change.",
        note="Whitespace is no longer ignored. Tests never pass padded input.",
        base={
            "flags.py": code(
                '''
                def parse_bool(s):
                    return s.strip().lower() in {"1", "true", "yes"}
                '''
            ),
            "test_flags.py": code(
                '''
                import unittest

                from flags import parse_bool


                class T(unittest.TestCase):
                    def test_parse_bool(self):
                        self.assertTrue(parse_bool("TRUE"))
                        self.assertFalse(parse_bool("no"))
                '''
            ),
        },
        head={
            "flags.py": code(
                '''
                def parse_bool(s):
                    return s.lower() in {"1", "true", "yes"}
                '''
            ),
        },
    ),
    Case(
        id="untested-title-case",
        category="untested",
        expect="buggy",
        title="Use str.title in title_case",
        description="Use str.title in title_case. No behavior change.",
        note="str.title mangles apostrophes (Don'T). Tests use plain words only.",
        base={
            "titles.py": code(
                '''
                def title_case(s):
                    return " ".join(w.capitalize() for w in s.split(" "))
                '''
            ),
            "test_titles.py": code(
                '''
                import unittest

                from titles import title_case


                class T(unittest.TestCase):
                    def test_title_case(self):
                        self.assertEqual(title_case("hello world"), "Hello World")
                '''
            ),
        },
        head={
            "titles.py": code(
                '''
                def title_case(s):
                    return s.title()
                '''
            ),
        },
    ),
]
