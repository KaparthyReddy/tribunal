import re
from typing import Any

from tribunal.llm import LLMClient, LLMError, complete_parsed
from tribunal.models import Claim, ClaimKind, Submission

MAX_CLAIMS = 12
MAX_CLAIM_CHARS = 500

SYSTEM = """You extract verifiable claims from a pull request written by a coding agent.
A claim is a factual statement about the change that could be checked by running code,
for example "fixes the crash when input is empty", "no behavior change", "adds tests for X",
"reduces runtime".
Rules:
- Only extract claims that are present in the text. Never invent claims.
- Each claim must be atomic and self-contained, written as a full sentence.
- Ignore pure statements of intent or style commentary.
- kind is one of: fixes, no_behavior_change, adds_tests, performance, other.
Output JSON only, no prose: {"claims": [{"text": "...", "kind": "..."}]}"""

NO_CHANGE_PATTERNS = tuple(
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"\bno\s+(?:other\s+|functional\s+|observable\s+)?behaviou?r(?:al)?\s+changes?\b",
        r"\bno\s+changes?\s+(?:in|to)\s+behaviou?r\b",
        r"\b(?:does\s+not|doesn't|won't|will\s+not)\s+(?:change|affect|alter)\s+(?:any\s+|existing\s+)?behaviou?r\b",
        r"\b(?:callers|users|clients|consumers)\s+(?:are|is)\s+(?:unaffected|not\s+affected)\b",
        r"\bbackwards?[\s-]+compatible\b",
        r"\bexisting\s+(?:calls|callers|usage|behaviou?r)\s+(?:is\s+|are\s+|remains?\s+|stays?\s+)?(?:unchanged|unaffected|intact)\b",
        r"\bpure\s+refactor(?:ing)?\b",
        r"\bsame\s+behaviou?r\b",
    )
)
KIND_LABELS = frozenset(kind.value for kind in ClaimKind if "_" in kind.value)
SENTENCES = re.compile(r"(?<=[.!?])\s+|\n+")


def matches_no_change(text: str) -> bool:
    return any(pattern.search(text) for pattern in NO_CHANGE_PATTERNS)


def _no_change_sentence(submission: Submission) -> str | None:
    for text in (submission.title, submission.description):
        for sentence in SENTENCES.split(text):
            sentence = sentence.strip()
            if sentence and matches_no_change(sentence):
                return sentence[:MAX_CLAIM_CHARS]
    return None


def deterministic_claims(submission: Submission) -> list[Claim]:
    sentence = _no_change_sentence(submission)
    if sentence is None:
        return []
    return [Claim(id="c1", text=sentence, kind=ClaimKind.NO_BEHAVIOR_CHANGE)]


def _user_prompt(submission: Submission) -> str:
    return f"Title:\n{submission.title}\n\nDescription:\n{submission.description}"


def _parse_kind(value: object) -> ClaimKind:
    try:
        return ClaimKind(str(value).strip().lower())
    except ValueError:
        return ClaimKind.OTHER


def _parse_items(data: Any) -> list[Any]:
    items = data.get("claims") if isinstance(data, dict) else data
    if not isinstance(items, list):
        raise LLMError("claim extraction did not return a list")
    return items


def extract_claims(llm: LLMClient, submission: Submission) -> list[Claim]:
    if not (submission.title.strip() or submission.description.strip()):
        return []

    items = complete_parsed(llm, SYSTEM, _user_prompt(submission), _parse_items)
    sentence = _no_change_sentence(submission)

    claims: list[Claim] = []
    seen: set[str] = set()
    for item in items:
        if not isinstance(item, dict):
            continue
        text = str(item.get("text", "")).strip()
        kind = _parse_kind(item.get("kind"))
        if text.lower() in KIND_LABELS:
            if text.lower() != ClaimKind.NO_BEHAVIOR_CHANGE.value or sentence is None:
                continue
            text, kind = sentence, ClaimKind.NO_BEHAVIOR_CHANGE
        if not text:
            continue
        if kind is not ClaimKind.NO_BEHAVIOR_CHANGE and matches_no_change(text):
            kind = ClaimKind.NO_BEHAVIOR_CHANGE
        key = text.lower()
        if key in seen:
            continue
        seen.add(key)
        claims.append(Claim(id=f"c{len(claims) + 1}", text=text[:MAX_CLAIM_CHARS], kind=kind))
        if len(claims) >= MAX_CLAIMS:
            break

    has_no_change = any(claim.kind is ClaimKind.NO_BEHAVIOR_CHANGE for claim in claims)
    if sentence is not None and not has_no_change and len(claims) < MAX_CLAIMS:
        claims.append(
            Claim(id=f"c{len(claims) + 1}", text=sentence, kind=ClaimKind.NO_BEHAVIOR_CHANGE)
        )
    return claims
