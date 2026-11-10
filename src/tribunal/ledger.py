from typing import Literal

from pydantic import BaseModel, ConfigDict

from tribunal.agents.judge import JudgePolicy
from tribunal.models import Severity
from tribunal.store import Store

MIN_HISTORY = 5
ELEVATED_BELOW = 0.75
HIGH_BELOW = 0.5

Scrutiny = Literal["standard", "elevated", "high"]


class AgentTrust(BaseModel):
    model_config = ConfigDict(frozen=True)

    agent: str
    repo: str | None = None
    passes: int
    fails: int
    inconclusive: int
    total: int
    score: float
    scrutiny: Scrutiny


def compute_trust(store: Store, agent: str, repo: str | None = None) -> AgentTrust:
    counts = store.agent_verdict_counts(agent, repo)
    passes = counts.get("pass", 0)
    fails = counts.get("fail", 0)
    inconclusive = counts.get("inconclusive", 0)
    total = passes + fails + inconclusive
    score = (passes + 1) / (total + 2)

    scrutiny: Scrutiny = "standard"
    if total >= MIN_HISTORY:
        if score < HIGH_BELOW:
            scrutiny = "high"
        elif score < ELEVATED_BELOW:
            scrutiny = "elevated"

    return AgentTrust(
        agent=agent,
        repo=repo,
        passes=passes,
        fails=fails,
        inconclusive=inconclusive,
        total=total,
        score=round(score, 4),
        scrutiny=scrutiny,
    )


def policy_for(trust: AgentTrust) -> JudgePolicy:
    if trust.scrutiny == "high":
        return JudgePolicy(fail_at=Severity.MEDIUM, review_at=Severity.LOW)
    if trust.scrutiny == "elevated":
        return JudgePolicy(fail_at=Severity.HIGH, review_at=Severity.LOW)
    return JudgePolicy()
