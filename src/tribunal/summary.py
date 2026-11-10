from typing import Any

from tribunal.agents.judge import SEVERITY_RANK
from tribunal.models import Finding, SignedReceipt

EMOJI = {"pass": "✅", "fail": "❌", "inconclusive": "⚠️"}


def _ordered(receipt: SignedReceipt) -> list[Finding]:
    return sorted(receipt.body.findings, key=lambda f: SEVERITY_RANK[f.severity], reverse=True)


def _claim_statuses(receipt: SignedReceipt) -> dict[str, str]:
    return {r.claim_id: r.status.value for r in receipt.body.claim_results}


def _cell(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ")


def summarize(receipt: SignedReceipt, max_findings: int = 10) -> dict[str, Any]:
    body = receipt.body
    statuses = _claim_statuses(receipt)
    findings = _ordered(receipt)
    return {
        "receipt_id": body.receipt_id,
        "submission_id": body.submission_id,
        "verdict": body.verdict.value,
        "rationale": body.rationale,
        "repo": body.repo,
        "base_sha": body.base_sha,
        "head_sha": body.head_sha,
        "digest": receipt.digest,
        "commands": len(body.commands),
        "claims": [
            {
                "id": claim.id,
                "text": claim.text,
                "kind": claim.kind.value,
                "status": statuses.get(claim.id, "unverifiable"),
            }
            for claim in body.claims
        ],
        "findings": [
            {"source": f.source, "title": f.title, "severity": f.severity.value}
            for f in findings[:max_findings]
        ],
        "findings_total": len(findings),
    }


def render_text(receipt: SignedReceipt, max_findings: int = 20) -> str:
    body = receipt.body
    statuses = _claim_statuses(receipt)
    findings = _ordered(receipt)
    lines = [
        f"VERDICT: {body.verdict.value.upper()}",
        f"repo {body.repo}  base {body.base_sha[:12]}  head {body.head_sha[:12]}",
        "",
        body.rationale,
    ]
    if body.claims:
        lines += ["", "Claims"]
        for claim in body.claims:
            status = statuses.get(claim.id, "unverifiable")
            lines.append(f"  [{status}] {claim.id}: {claim.text}")
    if findings:
        lines += ["", "Findings"]
        for finding in findings[:max_findings]:
            lines.append(f"  [{finding.severity.value}] {finding.source}: {finding.title}")
        if len(findings) > max_findings:
            lines.append(f"  ...and {len(findings) - max_findings} more")
    lines += [
        "",
        f"receipt {body.receipt_id}  commands {len(body.commands)}",
        f"sha256 {receipt.digest}",
    ]
    return "\n".join(lines)


def render_markdown(receipt: SignedReceipt, max_findings: int = 20) -> str:
    body = receipt.body
    statuses = _claim_statuses(receipt)
    findings = _ordered(receipt)
    lines = [
        f"### {EMOJI[body.verdict.value]} Tribunal: {body.verdict.value.upper()}",
        "",
        f"`{body.head_sha[:12]}` against base `{body.base_sha[:12]}`",
        "",
        body.rationale,
    ]
    if body.claims:
        lines += ["", "| Claim | Status |", "| --- | --- |"]
        for claim in body.claims:
            status = statuses.get(claim.id, "unverifiable")
            lines.append(f"| {_cell(claim.text)} | {status} |")
    if findings:
        lines += ["", "**Findings**", ""]
        for finding in findings[:max_findings]:
            lines.append(f"- `{finding.severity.value}` {finding.source}: {_cell(finding.title)}")
        if len(findings) > max_findings:
            lines.append(f"- ...and {len(findings) - max_findings} more")
    lines += [
        "",
        f"<sub>receipt `{body.receipt_id}` · {len(body.commands)} sandboxed command(s) · "
        f"sha256 `{receipt.digest[:16]}`</sub>",
    ]
    return "\n".join(lines)
