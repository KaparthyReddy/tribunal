import argparse
import html
import json
from pathlib import Path
from typing import Any

from benchmark.metrics import score

LABELS = {"tribunal": "Tribunal", "baseline": "LLM review"}

CSS = """
:root{color-scheme:light dark;--bg:#fff;--fg:#1a1a1a;--muted:#6b6b6b;--line:#d9d9d9;
--good:#e2f4e5;--warn:#fff2d1;--bad:#fbe0e0;--card:#f5f5f5}
@media (prefers-color-scheme:dark){:root{--bg:#121212;--fg:#ececec;--muted:#9a9a9a;
--line:#333;--good:#173a1e;--warn:#453913;--bad:#4a1a1a;--card:#1c1c1c}}
body{font:15px/1.5 system-ui,-apple-system,sans-serif;background:var(--bg);color:var(--fg);
max-width:1040px;margin:2rem auto;padding:0 1rem}
h1{margin:0 0 .25rem}h2{margin-top:2rem}
table{border-collapse:collapse;width:100%;margin:1rem 0}
th,td{border:1px solid var(--line);padding:.45rem .6rem;text-align:left;vertical-align:top}
th{background:var(--card)}
td.good{background:var(--good)}td.warn{background:var(--warn)}td.bad{background:var(--bad)}
.muted{color:var(--muted);font-size:.9em}
details summary{cursor:pointer;font-weight:600}
pre{white-space:pre-wrap;font-size:.85em;margin:.4rem 0}
code{font-size:.9em}
ul{margin:.3rem 0;padding-left:1.2rem}
.wrap{overflow-x:auto}
"""


def pct(count: int, total: int) -> str:
    if total == 0:
        return "-"
    return f"{count}/{total} ({count / total:.0%})"


def verdict_class(expect: str, outcome: str | None) -> str:
    if outcome in (None, "error"):
        return "muted"
    if outcome == "inconclusive":
        return "warn"
    correct = outcome == "fail" if expect == "buggy" else outcome == "pass"
    return "good" if correct else "bad"


def _scores(results: dict[str, Any]) -> dict[str, dict[str, Any]]:
    cases = results.get("cases", [])
    return {key: score(cases, key) for key in LABELS if any(key in case for case in cases)}


def headline_rows(scores: dict[str, dict[str, Any]]) -> list[tuple[str, dict[str, str]]]:
    spec: list[tuple[str, Any]] = [
        ("Buggy changes", lambda s: str(s["buggy"]["n"])),
        ("Caught (verdict fail)", lambda s: pct(s["buggy"]["caught"], s["buggy"]["n"])),
        (
            "Flagged for review (inconclusive)",
            lambda s: pct(s["buggy"]["flagged"], s["buggy"]["n"]),
        ),
        ("Missed (false green)", lambda s: pct(s["buggy"]["missed"], s["buggy"]["n"])),
        ("Clean changes", lambda s: str(s["clean"]["n"])),
        ("Passed", lambda s: pct(s["clean"]["passed"], s["clean"]["n"])),
        ("Flagged for review", lambda s: pct(s["clean"]["flagged"], s["clean"]["n"])),
        ("Wrongly blocked", lambda s: pct(s["clean"]["blocked"], s["clean"]["n"])),
    ]
    return [(label, {key: fn(value) for key, value in scores.items()}) for label, fn in spec]


def headline_markdown(results: dict[str, Any]) -> str:
    scores = _scores(results)
    if not scores:
        return "No results."
    keys = list(scores)
    lines = [
        "| Metric | " + " | ".join(LABELS[key] for key in keys) + " |",
        "| --- |" + " --- |" * len(keys),
    ]
    for label, values in headline_rows(scores):
        lines.append(f"| {label} | " + " | ".join(values[key] for key in keys) + " |")
    errors = {key: value["errors"] for key, value in scores.items() if value["errors"]}
    if errors:
        text = ", ".join(f"{LABELS[key]} {count}" for key, count in errors.items())
        lines += ["", f"Errored cases excluded from the rates: {text}."]
    return "\n".join(lines)


def _meta_line(meta: dict[str, Any]) -> str:
    return (
        f"Model `{meta.get('provider', '?')}/{meta.get('model', '?')}` · "
        f"sandbox `{meta.get('sandbox_image', '?')}` · "
        f"{meta.get('cases_total', '?')} cases · {meta.get('started_at', '')}"
    )


def render_markdown(results: dict[str, Any]) -> str:
    lines = [
        "# Tribunal benchmark",
        "",
        _meta_line(results.get("meta", {})),
        "",
        headline_markdown(results),
        "",
        "## Cases",
        "",
        "| Case | Category | Truth | Tribunal | LLM review |",
        "| --- | --- | --- | --- | --- |",
    ]
    for case in results.get("cases", []):
        tribunal = case.get("tribunal", {}).get("outcome", "-")
        baseline = case.get("baseline", {}).get("outcome", "-")
        lines.append(
            f"| {case['id']} | {case['category']} | {case['expect']} | {tribunal} | {baseline} |"
        )
    return "\n".join(lines) + "\n"


def _detail(data: dict[str, Any]) -> str:
    esc = html.escape
    parts: list[str] = []
    if data.get("error"):
        parts.append(f"<p>{esc(str(data['error']))}</p>")
    if data.get("rationale"):
        parts.append(f"<pre>{esc(str(data['rationale']))}</pre>")
    if data.get("reason"):
        parts.append(f"<p>{esc(str(data['reason']))}</p>")
    findings = data.get("findings") or []
    if findings:
        items = "".join(
            f"<li><code>{esc(str(f['severity']))}</code> {esc(str(f['title']))}</li>"
            for f in findings
        )
        parts.append(f"<ul>{items}</ul>")
    if "seconds" in data:
        parts.append(f'<p class="muted">{esc(str(data["seconds"]))}s</p>')
    return "".join(parts)


def _cell(case: dict[str, Any], key: str) -> str:
    data = case.get(key)
    if data is None:
        return '<td class="muted">-</td>'
    outcome = str(data.get("outcome", "error"))
    cls = verdict_class(case["expect"], outcome)
    detail = _detail(data)
    summary = html.escape(outcome)
    inner = f"<details><summary>{summary}</summary>{detail}</details>" if detail else summary
    return f'<td class="{cls}">{inner}</td>'


def render_html(results: dict[str, Any]) -> str:
    esc = html.escape
    scores = _scores(results)
    keys = list(scores)
    meta = results.get("meta", {})

    head_cells = "".join(f"<th>{esc(LABELS[key])}</th>" for key in keys)
    headline = "".join(
        f"<tr><td>{esc(label)}</td>"
        + "".join(f"<td>{esc(values[key])}</td>" for key in keys)
        + "</tr>"
        for label, values in headline_rows(scores)
    )

    case_rows = []
    for case in results.get("cases", []):
        note = f'<br><span class="muted">{esc(case["note"])}</span>' if case.get("note") else ""
        case_rows.append(
            "<tr>"
            f"<td><strong>{esc(case['id'])}</strong><br>"
            f'<span class="muted">{esc(case["title"])}</span>{note}</td>'
            f"<td>{esc(case['category'])}</td>"
            f"<td>{esc(case['expect'])}</td>"
            f"{_cell(case, 'tribunal')}{_cell(case, 'baseline')}"
            "</tr>"
        )

    body = (
        "<h1>Tribunal benchmark</h1>"
        f'<p class="muted">{esc(_meta_line(meta))}</p>'
        '<div class="wrap"><table>'
        f"<tr><th>Metric</th>{head_cells}</tr>{headline}</table></div>"
        "<p>Green is the right call, amber is flagged for human review, red is wrong. "
        "A caught bug is a <code>fail</code> verdict. A clean change should <code>pass</code>. "
        "The LLM review baseline sees only the title, description and diff.</p>"
        "<h2>Cases</h2>"
        '<div class="wrap"><table>'
        "<tr><th>Case</th><th>Category</th><th>Truth</th><th>Tribunal</th><th>LLM review</th></tr>"
        + "".join(case_rows)
        + "</table></div>"
    )
    return (
        '<!doctype html>\n<html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        "<title>Tribunal benchmark</title><style>" + CSS + "</style></head><body>" + body
        + "</body></html>\n"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m benchmark.report",
        description="Render results.json as report.md and report.html.",
    )
    parser.add_argument("--results", type=Path, default=Path("benchmark/results/results.json"))
    parser.add_argument("--out-dir", type=Path, default=None)
    args = parser.parse_args(argv)

    results = json.loads(args.results.read_text(encoding="utf-8"))
    out_dir = args.out_dir or args.results.parent
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "report.md").write_text(render_markdown(results), encoding="utf-8")
    (out_dir / "report.html").write_text(render_html(results), encoding="utf-8")
    print(f"wrote {out_dir / 'report.html'}")
    print(f"wrote {out_dir / 'report.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
