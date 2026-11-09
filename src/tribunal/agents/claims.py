from tribunal.llm import LLMClient, LLMError, complete_json
from tribunal.models import Claim, ClaimKind, Submission

MAX_CLAIMS = 12
MAX_CLAIM_CHARS = 500

SYSTEM = """You extract verifiable claims from a pull request written by a coding agent.
A claim is a factual statement about the change that could be checked by running code,
for example "fixes the crash when input is empty", "no behavior change", "adds tests for X",
"reduces runtime".
Rules:
- Only extract claims that are present in the text. Never invent claims.
- Each claim must be atomic and self-contained.
- Ignore pure statements of intent or style commentary.
- kind is one of: fixes, no_behavior_change, adds_tests, performance, other.
Output JSON only, no prose: {"claims": [{"text": "...", "kind": "..."}]}"""


def _user_prompt(submission: Submission) -> str:
    return f"Title:\n{submission.title}\n\nDescription:\n{submission.description}"


def _parse_kind(value: object) -> ClaimKind:
    try:
        return ClaimKind(str(value).strip().lower())
    except ValueError:
        return ClaimKind.OTHER


def extract_claims(llm: LLMClient, submission: Submission) -> list[Claim]:
    if not (submission.title.strip() or submission.description.strip()):
        return []

    data = complete_json(llm, SYSTEM, _user_prompt(submission))
    items = data.get("claims") if isinstance(data, dict) else data
    if not isinstance(items, list):
        raise LLMError("claim extraction did not return a list")

    claims: list[Claim] = []
    seen: set[str] = set()
    for item in items:
        if not isinstance(item, dict):
            continue
        text = str(item.get("text", "")).strip()
        key = text.lower()
        if not text or key in seen:
            continue
        seen.add(key)
        claims.append(
            Claim(
                id=f"c{len(claims) + 1}",
                text=text[:MAX_CLAIM_CHARS],
                kind=_parse_kind(item.get("kind")),
            )
        )
        if len(claims) >= MAX_CLAIMS:
            break
    return claims
