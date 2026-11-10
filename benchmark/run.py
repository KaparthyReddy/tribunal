import argparse
import json
import sys
import tempfile
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from benchmark.baseline import review
from benchmark.cases import ALL_CASES
from benchmark.model import TEST_COMMAND, Case, build_repo
from benchmark.report import headline_markdown
from tribunal import __version__, gitutil
from tribunal.config import Settings
from tribunal.llm import LLMClient, LLMError, make_llm, preflight
from tribunal.pipeline import build_pipeline
from tribunal.sandbox import (
    SandboxPolicy,
    SandboxRunner,
    SandboxUnavailableError,
    docker_available,
)

SystemFn = Callable[[Case, Path, str, str], dict[str, Any]]
Progress = Callable[[int, int, list[dict[str, Any]]], None]


def select_cases(only: str | None) -> list[Case]:
    if not only:
        return list(ALL_CASES)
    wanted = [item.strip() for item in only.split(",") if item.strip()]
    by_id = {case.id: case for case in ALL_CASES}
    unknown = [item for item in wanted if item not in by_id]
    if unknown:
        raise ValueError(f"unknown case id(s): {', '.join(unknown)}")
    return [by_id[item] for item in wanted]


def _timed(fn: SystemFn, case: Case, repo: Path, base: str, head: str) -> dict[str, Any]:
    started = time.monotonic()
    try:
        result = fn(case, repo, base, head)
    except Exception as exc:
        result = {"outcome": "error", "error": f"{type(exc).__name__}: {exc}"[:500]}
    result["seconds"] = round(time.monotonic() - started, 2)
    return result


def evaluate(
    cases: list[Case],
    workdir: Path,
    *,
    tribunal: SystemFn | None = None,
    baseline: SystemFn | None = None,
    progress: Progress | None = None,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for index, case in enumerate(cases, start=1):
        repo, base_sha, head_sha = build_repo(case, workdir)
        row: dict[str, Any] = {
            "id": case.id,
            "category": case.category,
            "expect": case.expect,
            "title": case.title,
            "note": case.note,
        }
        if tribunal is not None:
            row["tribunal"] = _timed(tribunal, case, repo, base_sha, head_sha)
        if baseline is not None:
            row["baseline"] = _timed(baseline, case, repo, base_sha, head_sha)
        rows.append(row)
        if progress is not None:
            progress(index, len(cases), rows)
    return rows


def make_tribunal_fn(settings: Settings, receipts_dir: Path) -> SystemFn:
    pipeline = build_pipeline(settings)

    def run(case: Case, repo: Path, base: str, head: str) -> dict[str, Any]:
        submission = pipeline.submit(
            repo_path=repo,
            base=base,
            head=head,
            repo=case.id,
            title=case.title,
            description=case.description,
            agent="benchmark",
            test_command=TEST_COMMAND,
        )
        receipt = pipeline.run(submission.id)
        receipts_dir.mkdir(parents=True, exist_ok=True)
        (receipts_dir / f"{case.id}.json").write_text(
            receipt.model_dump_json(indent=2), encoding="utf-8"
        )
        return {
            "outcome": receipt.body.verdict.value,
            "receipt_id": receipt.body.receipt_id,
            "rationale": receipt.body.rationale,
            "findings": [
                {"severity": finding.severity.value, "title": finding.title}
                for finding in receipt.body.findings[:6]
            ],
        }

    return run


def make_baseline_fn(llm: LLMClient) -> SystemFn:
    def run(case: Case, repo: Path, base: str, head: str) -> dict[str, Any]:
        diff = gitutil.diff(repo, base, head)
        result = review(llm, case.title, case.description, diff)
        return {"outcome": result.outcome, "reason": result.reason}

    return run


def write_results(out: Path, meta: dict[str, Any], rows: list[dict[str, Any]]) -> dict[str, Any]:
    results = {"meta": {**meta, "cases_total": len(rows)}, "cases": rows}
    out.mkdir(parents=True, exist_ok=True)
    (out / "results.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
    return results


def _describe(row: dict[str, Any]) -> str:
    parts = []
    seconds = 0.0
    for key in ("tribunal", "baseline"):
        if key in row:
            parts.append(f"{key}={row[key]['outcome']}")
            seconds += row[key].get("seconds", 0.0)
    return f"{row['id']:<26} {'  '.join(parts)}  ({seconds:.0f}s)"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m benchmark.run",
        description="Score Tribunal against a plain LLM review on seeded-bug changes.",
    )
    parser.add_argument("--only", help="comma separated case ids")
    parser.add_argument("--out", type=Path, default=Path("benchmark/results"))
    parser.add_argument("--skip-baseline", action="store_true")
    parser.add_argument("--skip-tribunal", action="store_true")
    parser.add_argument("--list", action="store_true", help="list cases and exit")
    args = parser.parse_args(argv)

    try:
        cases = select_cases(args.only)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    if args.list:
        for case in cases:
            print(f"{case.id:<26} {case.category:<12} {case.expect:<6} {case.title}")
        return 0
    if args.skip_baseline and args.skip_tribunal:
        print("error: nothing to run", file=sys.stderr)
        return 2

    with tempfile.TemporaryDirectory(prefix="tribunal-bench-") as tmp:
        root = Path(tmp)
        settings = Settings(data_dir=root / "data", ledger_enabled=False)

        try:
            preflight(settings)
            if not args.skip_tribunal:
                if not docker_available():
                    raise SandboxUnavailableError("docker is not available")
                SandboxRunner(SandboxPolicy.from_settings(settings)).ensure_image()
        except (LLMError, SandboxUnavailableError) as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 3

        tribunal_fn = (
            None if args.skip_tribunal else make_tribunal_fn(settings, args.out / "receipts")
        )
        baseline_fn = None if args.skip_baseline else make_baseline_fn(make_llm(settings))

        meta = {
            "started_at": datetime.now(UTC).isoformat(timespec="seconds"),
            "provider": settings.llm_provider,
            "model": (
                settings.ollama_model if settings.llm_provider == "ollama" else settings.llm_model
            ),
            "sandbox_image": settings.sandbox_image,
            "tribunal_version": __version__,
        }

        def progress(index: int, total: int, rows: list[dict[str, Any]]) -> None:
            print(f"[{index}/{total}] {_describe(rows[-1])}", flush=True)
            write_results(args.out, meta, rows)

        rows = evaluate(
            cases,
            root / "repos",
            tribunal=tribunal_fn,
            baseline=baseline_fn,
            progress=progress,
        )

    results = write_results(args.out, meta, rows)
    print()
    print(headline_markdown(results))
    print(f"\nresults: {args.out / 'results.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
