from benchmark.cases import clean, false_claims, regressions, untested
from benchmark.model import Case

ALL_CASES: list[Case] = [
    *regressions.CASES,
    *untested.CASES,
    *false_claims.CASES,
    *clean.CASES,
]


def _check_unique(cases: list[Case]) -> None:
    seen: set[str] = set()
    for case in cases:
        if case.id in seen:
            raise ValueError(f"duplicate case id {case.id}")
        seen.add(case.id)


_check_unique(ALL_CASES)
