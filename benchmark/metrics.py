from typing import Any

VALID = frozenset({"pass", "fail", "inconclusive"})


def rate(count: int, total: int) -> float | None:
    return None if total == 0 else count / total


def score(cases: list[dict[str, Any]], system: str) -> dict[str, Any]:
    present = [case for case in cases if system in case]
    valid = [case for case in present if case[system].get("outcome") in VALID]
    buggy = [case for case in valid if case["expect"] == "buggy"]
    clean = [case for case in valid if case["expect"] == "clean"]

    def count(group: list[dict[str, Any]], outcome: str) -> int:
        return sum(1 for case in group if case[system]["outcome"] == outcome)

    caught = count(buggy, "fail")
    flagged_buggy = count(buggy, "inconclusive")
    missed = count(buggy, "pass")
    passed = count(clean, "pass")
    flagged_clean = count(clean, "inconclusive")
    blocked = count(clean, "fail")

    return {
        "system": system,
        "cases": len(present),
        "errors": len(present) - len(valid),
        "buggy": {
            "n": len(buggy),
            "caught": caught,
            "flagged": flagged_buggy,
            "missed": missed,
            "catch_rate": rate(caught, len(buggy)),
            "flag_rate": rate(caught + flagged_buggy, len(buggy)),
            "false_green_rate": rate(missed, len(buggy)),
        },
        "clean": {
            "n": len(clean),
            "passed": passed,
            "flagged": flagged_clean,
            "blocked": blocked,
            "false_block_rate": rate(blocked, len(clean)),
            "false_flag_rate": rate(blocked + flagged_clean, len(clean)),
        },
    }
