from tribunal.graph import changed_ranges, parse_unified_diff_ranges


def test_parse_multiple_files_and_hunks() -> None:
    diff = "\n".join(
        [
            "diff --git a/a.py b/a.py",
            "--- a/a.py",
            "+++ b/a.py",
            "@@ -2 +2 @@",
            "-y = 2",
            "+y = 20",
            "@@ -3,0 +4,2 @@",
            "+w = 4",
            "+v = 5",
            "diff --git a/new.py b/new.py",
            "--- /dev/null",
            "+++ b/new.py",
            "@@ -0,0 +1,3 @@",
            "+a",
            "+b",
            "+c",
            "diff --git a/gone.py b/gone.py",
            "--- a/gone.py",
            "+++ /dev/null",
            "@@ -1,2 +0,0 @@",
            "-a",
            "-b",
        ]
    )
    assert parse_unified_diff_ranges(diff) == {
        "a.py": [(2, 2), (4, 5)],
        "new.py": [(1, 3)],
    }


def test_deletion_only_hunk_maps_to_position() -> None:
    diff = "\n".join(["--- a/a.py", "+++ b/a.py", "@@ -5,2 +4,0 @@", "-x", "-y"])
    assert parse_unified_diff_ranges(diff) == {"a.py": [(4, 4)]}


def test_hunk_body_lines_that_look_like_headers() -> None:
    diff = "\n".join(
        [
            "--- a/a.py",
            "+++ b/a.py",
            "@@ -3 +2,0 @@",
            "--- removed comment",
            "@@ -10,0 +10,2 @@",
            "+++ added",
            "+b",
        ]
    )
    assert parse_unified_diff_ranges(diff) == {"a.py": [(2, 2), (10, 11)]}


def test_changed_ranges_from_git(make_repo) -> None:
    repo, shas = make_repo(
        [
            {"a.py": "x = 1\ny = 2\nz = 3\n"},
            {"a.py": "x = 1\ny = 20\nz = 3\nw = 4\n"},
        ]
    )
    assert changed_ranges(repo, shas[0], shas[1]) == {"a.py": [(2, 2), (4, 4)]}
