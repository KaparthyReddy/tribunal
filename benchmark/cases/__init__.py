from benchmark.cases import clean, false_claims, holdout, holdout2, regressions, untested
from benchmark.model import Case

ALL_CASES: list[Case] = [
    *regressions.CASES,
    *untested.CASES,
    *false_claims.CASES,
    *clean.CASES,
]

HOLDOUT_CASES: list[Case] = list(holdout.CASES)

HOLDOUT2_CASES: list[Case] = list(holdout2.CASES)

CASE_SETS: dict[str, list[Case]] = {
    "dev": ALL_CASES,
    "holdout": HOLDOUT_CASES,
    "holdout2": HOLDOUT2_CASES,
}


def _check_unique(cases: list[Case]) -> None:
    seen: set[str] = set()
    for case in cases:
        if case.id in seen:
            raise ValueError(f"duplicate case id {case.id}")
        seen.add(case.id)


_check_unique([*ALL_CASES, *HOLDOUT_CASES, *HOLDOUT2_CASES])
