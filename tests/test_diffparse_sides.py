from tribunal.graph import FileChange, changed_sides, parse_unified_diff_sides

DIFF = "\n".join(
    [
        "--- a/a.py",
        "+++ b/a.py",
        "@@ -2 +2 @@",
        "-y = 2",
        "+y = 20",
        "@@ -3,0 +4,2 @@",
        "+w = 4",
        "+v = 5",
        "--- a/gone.py",
        "+++ /dev/null",
        "@@ -1,2 +0,0 @@",
        "-a",
        "-b",
        "--- /dev/null",
        "+++ b/new.py",
        "@@ -0,0 +1,3 @@",
        "+a",
        "+b",
        "+c",
    ]
)


def test_sides_for_edits_additions_and_new_files() -> None:
    assert parse_unified_diff_sides(DIFF) == {
        "a.py": FileChange(added=((2, 2), (4, 5)), removed=((2, 2),)),
        "new.py": FileChange(added=((1, 3),), removed=()),
    }


def test_changed_sides_from_git(make_repo) -> None:
    repo, shas = make_repo(
        [
            {"a.py": "x = 1\ny = 2\nz = 3\n"},
            {"a.py": "x = 1\ny = 20\nz = 3\nw = 4\n"},
        ]
    )
    assert changed_sides(repo, shas[0], shas[1]) == {
        "a.py": FileChange(added=((2, 2), (4, 4)), removed=((2, 2),))
    }
