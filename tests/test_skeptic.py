import json
from pathlib import Path

from tribunal.agents import AuditContext, Evidence, Skeptic
from tribunal.llm import ScriptedLLM
from tribunal.models import Severity, Submission

PROBE = (
    "import unittest\n\n\nclass T(unittest.TestCase):\n"
    "    def test_x(self):\n        self.assertTrue(True)\n"
)
LIB = "def f(a):\n    return a + 1\n"


def _llm(*codes: str) -> ScriptedLLM:
    probes = [{"name": f"p{i}", "code": code} for i, code in enumerate(codes)]
    return ScriptedLLM([json.dumps({"probes": probes})])


def _ctx(tmp_path: Path, test_command: list[str] | None = None) -> AuditContext:
    base = tmp_path / "base"
    head = tmp_path / "head"
    for root in (base, head):
        root.mkdir()
        (root / "lib.py").write_text(LIB)
    submission = Submission(
        repo="o/r",
        repo_path=str(tmp_path),
        base_sha="a" * 40,
        head_sha="b" * 40,
        title="t",
        test_command=test_command or [],
    )
    return AuditContext(
        submission=submission,
        base_dir=base,
        head_dir=head,
        evidence=Evidence(),
        diff="diff",
    )


def _severities(result) -> list[Severity]:
    return [f.severity for f in result.findings]


def test_probe_regression_is_high(tmp_path: Path, make_runner) -> None:
    seen: list[str] = []

    def handler(workdir: Path, argv: list[str]) -> tuple[int, str, str]:
        assert (workdir / "tribunal_probes" / "probe_1.py").exists()
        seen.append(workdir.name)
        return (1, "", "FAIL") if workdir.name == "head" else (0, "OK", "")

    ctx = _ctx(tmp_path)
    result = Skeptic(_llm(PROBE), make_runner(handler)).attack(ctx, {})

    assert seen == ["head", "base"]
    highs = [f for f in result.findings if f.severity is Severity.HIGH]
    assert len(highs) == 1
    assert "broke the change" in highs[0].title
    assert not (ctx.head_dir / "tribunal_probes").exists()
    assert not (ctx.base_dir / "tribunal_probes").exists()


def test_probe_failing_on_both_is_low(tmp_path: Path, make_runner) -> None:
    runner = make_runner(lambda workdir, argv: (1, "", "FAIL"))
    result = Skeptic(_llm(PROBE), runner).attack(_ctx(tmp_path), {})
    assert Severity.HIGH not in _severities(result)
    assert any("both base and head" in f.title for f in result.findings)


def test_passing_probe_creates_no_blocking_findings(tmp_path: Path, make_runner) -> None:
    runner = make_runner(lambda workdir, argv: (0, "OK", ""))
    result = Skeptic(_llm(PROBE), runner).attack(_ctx(tmp_path), {})
    assert {Severity.MEDIUM, Severity.HIGH, Severity.LOW}.isdisjoint(_severities(result))
    assert [workdir.name for workdir, _ in runner.calls] == ["head"]


def test_invalid_probe_code_is_dropped(tmp_path: Path, make_runner) -> None:
    runner = make_runner(lambda workdir, argv: (0, "", ""))
    result = Skeptic(_llm("def ("), runner).attack(_ctx(tmp_path), {})
    assert runner.calls == []
    assert any("no valid probes" in f.title for f in result.findings)


def test_infra_failure_skips_base_run(tmp_path: Path, make_runner) -> None:
    runner = make_runner(lambda workdir, argv: (127, "", "no python"))
    result = Skeptic(_llm(PROBE), runner).attack(_ctx(tmp_path), {})
    assert len(runner.calls) == 1
    assert any("could not run" in f.title for f in result.findings)


def test_generation_failure_is_low(tmp_path: Path, make_runner) -> None:
    runner = make_runner(lambda workdir, argv: (0, "", ""))
    result = Skeptic(ScriptedLLM(["junk"]), runner).attack(_ctx(tmp_path), {})
    assert any("generation failed" in f.title for f in result.findings)
    assert runner.calls == []


def test_mutation_survivors_and_restore(tmp_path: Path, make_runner) -> None:
    def handler(workdir: Path, argv: list[str]) -> tuple[int, str, str]:
        content = (workdir / "lib.py").read_text()
        if "a - 1" in content or "return None" in content:
            return 1, "FAILED", ""
        return 0, "ok", ""

    ctx = _ctx(tmp_path, test_command=["pytest"])
    result = Skeptic(_llm(), make_runner(handler)).attack(ctx, {"lib.py": [(1, 2)]})

    survivors = [f for f in result.findings if f.title.startswith("Surviving mutant")]
    assert len(survivors) == 1
    assert "1 -> 2" in survivors[0].title
    assert survivors[0].severity is Severity.MEDIUM
    summary = [f for f in result.findings if f.title.startswith("Mutation score")]
    assert "2/3" in summary[0].title
    assert (ctx.head_dir / "lib.py").read_text() == LIB
    assert len(ctx.evidence.commands) == 4


def test_mutation_skipped_without_test_command(tmp_path: Path, make_runner) -> None:
    runner = make_runner(lambda workdir, argv: (0, "", ""))
    result = Skeptic(_llm(), runner).attack(_ctx(tmp_path), {"lib.py": [(1, 2)]})
    assert any("no test command" in f.title for f in result.findings)


def test_mutation_skipped_when_baseline_fails(tmp_path: Path, make_runner) -> None:
    runner = make_runner(lambda workdir, argv: (1, "FAILED", ""))
    ctx = _ctx(tmp_path, test_command=["pytest"])
    result = Skeptic(_llm(), runner).attack(ctx, {"lib.py": [(1, 2)]})
    assert any("does not pass on head" in f.title for f in result.findings)
    assert not any(f.title.startswith("Surviving mutant") for f in result.findings)
