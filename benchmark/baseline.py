from dataclasses import dataclass

from tribunal.llm import LLMClient, LLMError, complete_json

MAX_DIFF_CHARS = 12000

SYSTEM = """You are a strict senior code reviewer deciding whether to approve a pull request.
Reject it if it introduces a bug, changes behavior the description says is unchanged,
or does not do what the description claims. Approve it only if the change is correct.
Output JSON only, no prose: {"decision": "approve" or "reject", "reason": "one sentence"}"""


@dataclass(frozen=True)
class BaselineResult:
    outcome: str
    reason: str


def review(llm: LLMClient, title: str, description: str, diff: str) -> BaselineResult:
    user = f"PR title: {title}\n\nPR description:\n{description}\n\nDiff:\n{diff[:MAX_DIFF_CHARS]}"
    data = complete_json(llm, SYSTEM, user)
    if not isinstance(data, dict):
        raise LLMError("review must be a JSON object")
    decision = str(data.get("decision", "")).strip().lower()
    if decision not in {"approve", "reject"}:
        raise LLMError(f"unexpected decision {decision!r}")
    return BaselineResult(
        outcome="pass" if decision == "approve" else "fail",
        reason=str(data.get("reason", ""))[:500],
    )
