import json
import os
from dataclasses import dataclass
from pathlib import Path

import httpx

from tribunal.models import SignedReceipt

MARKER = "<!-- tribunal-verdict -->"
DEFAULT_API_URL = "https://api.github.com"
PER_PAGE = 100
MAX_PAGES = 10


class CIError(RuntimeError):
    pass


@dataclass(frozen=True)
class PRContext:
    repo: str
    number: int
    base_sha: str
    head_sha: str
    title: str
    body: str
    author: str


def load_pr_context(event_path: str | Path) -> PRContext:
    try:
        event = json.loads(Path(event_path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise CIError(f"cannot read event payload: {exc}") from exc

    pr = event.get("pull_request") if isinstance(event, dict) else None
    if not isinstance(pr, dict):
        raise CIError("this workflow run is not a pull_request event")

    try:
        return PRContext(
            repo=event["repository"]["full_name"],
            number=int(pr["number"]),
            base_sha=pr["base"]["sha"],
            head_sha=pr["head"]["sha"],
            title=pr.get("title") or "",
            body=pr.get("body") or "",
            author=(pr.get("user") or {}).get("login") or "unknown",
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise CIError(f"unexpected pull_request payload: {exc}") from exc


def write_step_summary(markdown: str, path: str | None = None) -> bool:
    target = path or os.environ.get("GITHUB_STEP_SUMMARY")
    if not target:
        return False
    with Path(target).open("a", encoding="utf-8") as handle:
        handle.write(markdown + "\n")
    return True


def write_outputs(receipt: SignedReceipt, path: str | None = None) -> bool:
    target = path or os.environ.get("GITHUB_OUTPUT")
    if not target:
        return False
    body = receipt.body
    lines = [
        f"verdict={body.verdict.value}",
        f"receipt-id={body.receipt_id}",
        f"digest={receipt.digest}",
        f"head-sha={body.head_sha}",
    ]
    with Path(target).open("a", encoding="utf-8") as handle:
        handle.write("\n".join(lines) + "\n")
    return True


def _find_comment(client: httpx.Client, repo: str, number: int) -> int | None:
    for page in range(1, MAX_PAGES + 1):
        response = client.get(
            f"/repos/{repo}/issues/{number}/comments",
            params={"per_page": PER_PAGE, "page": page},
        )
        response.raise_for_status()
        items = response.json()
        for item in items:
            user = item.get("user") or {}
            if user.get("type") == "Bot" and MARKER in (item.get("body") or ""):
                return int(item["id"])
        if len(items) < PER_PAGE:
            break
    return None


def upsert_comment(
    repo: str,
    number: int,
    token: str,
    markdown: str,
    *,
    client: httpx.Client | None = None,
    api_url: str | None = None,
) -> str:
    body = f"{MARKER}\n{markdown}"
    owned = client is None
    if client is None:
        client = httpx.Client(
            base_url=api_url or os.environ.get("GITHUB_API_URL") or DEFAULT_API_URL,
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
            timeout=30,
        )
    try:
        existing = _find_comment(client, repo, number)
        if existing is None:
            response = client.post(f"/repos/{repo}/issues/{number}/comments", json={"body": body})
        else:
            response = client.patch(
                f"/repos/{repo}/issues/comments/{existing}", json={"body": body}
            )
        response.raise_for_status()
        return str(response.json()["html_url"])
    except httpx.HTTPError as exc:
        raise CIError(f"cannot post comment: {exc}") from exc
    finally:
        if owned:
            client.close()
