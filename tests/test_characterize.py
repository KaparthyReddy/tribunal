import json
from pathlib import Path

import pytest

from tribunal.agents import (
    AgentResult,
    AuditContext,
    Characterizer,
    Evidence,
    merge_characterization,
)
from tribunal.agents.characterize import (
    ARGV,
    CHAR_DIR,
    DRIVER,
    Target,
    module_name,
    parse_calls,
    parse_results,
    select_targets,
)
from tribunal.llm import LLMError, ScriptedLLM
from tribunal.models import (
    Claim,
    ClaimKind,
    ClaimResult,
    ClaimStatus,
    Finding,
    Severity,
    Submission,
)
from tribunal.sandbox import SandboxPolicy, SandboxRunner, docker_available

BASE_SRC = 'def greet(name, punct="!"):\n    return "Hello, " + name + punct\n'
HEAD_SRC = 'def greet(name, punct="."):\n    return "Hello, " + name + punct\n'
RANGES = {"greet.py": [(1, 2)]}
NO_CHANGE = Claim(id="c1", text="no change", kind=ClaimKind.NO_BEHAVIOR_CHANGE)
FIXES = Claim(id="c1", text="fixes the crash", kind=ClaimKind.FIXES)

needs_docker = pytest.mark.skipif(not docker_available(), reason="docker unavailable")


def _ctx(tmp_path: Path, base_src: str = BASE_SRC, head_src: str = HEAD_SRC) -> AuditContext:
    base = tmp_path / "base"
    head = tmp_path / "head"
    for root, source in ((base, base_src), (head, head_src)):
        root.mkdir()
        (root / "greet.py").write_text(source)
    submission = Submission(
        repo="o/r",
        repo_path=str(tmp_path),
        base_sha="a" * 40,
        head_sha="b" * 40,
        title="t",
    )
    return AuditContext(
        submission=submission,
        base_dir=base,
        head_dir=head,
        evidence=Evidence(),
        diff="diff",
    )


def _call(*args, claim: str | None = None) -> dict:
    return {
        "module": "greet",
        "function": "greet",
        "args": list(args),
        "kwargs": {},
        "claim": claim,
    }


def _llm(*calls: dict) -> ScriptedLLM:
    return ScriptedLLM([json.dumps({"calls": list(calls)})])


def _ok(index: int, value: str) -> str:
    return json.dumps({"i": index, "ok": True, "value": value})


def _exc(index: int, name: str) -> str:
    return json.dumps({"i": index, "ok": False, "exc": name, "msg": ""})


def _handler(base_out: str, head_outs: list[str]):
    state = {"head": 0}

    def handler(workdir: Path, argv: list[str]) -> tuple[int, str, str]:
        assert (workdir / CHAR_DIR / "calls.json").exists()
        if workdir.name == "base":
            return 0, base_out, ""
        out = head_outs[min(state["head"], len(head_outs) - 1)]
        state["head"] += 1
        return 0, out, ""

    return handler


def test_module_name() -> None:
    assert module_name("pkg/mod.py") == "pkg.mod"
    assert module_name("pkg/__init__.py") == "pkg"
    assert module_name("top.py") == "top"
    assert module_name("my-dir/x.py") is None
    assert module_name("README.md") is None
    assert module_name("__init__.py") is None


def test_select_targets(tmp_path: Path) -> None:
    base_src = BASE_SRC + "\n\nclass K:\n    def m(self):\n        return 1\n"
    head_src = HEAD_SRC + "\n\nclass K:\n    def m(self):\n        return 1\n"
    head_src += "\n\ndef fresh():\n    return 2\n"
    ctx = _ctx(tmp_path, base_src, head_src)
    targets = select_targets(ctx.base_dir, ctx.head_dir, {"greet.py": [(1, 11)]})
    assert [(t.module, t.function) for t in targets] == [("greet", "greet")]
    assert "punct" in targets[0].source


def test_parse_calls_filters() -> None:
    targets = [Target("greet.py", "greet", "greet", "")]
    data = {
        "calls": [
            _call("a", claim="c1"),
            _call("a"),
            {"module": "greet", "function": "other", "args": []},
            {"module": "greet", "function": "greet", "args": "bad"},
            {"module": "greet", "function": "greet", "args": [], "kwargs": {"p": "?"}, "claim": "c9"},
            "junk",
        ]
    }
    calls = parse_calls(data, targets, [FIXES], limit=10)
    assert len(calls) == 2
    assert calls[0].claim == "c1"
    assert calls[1].claim is None
    assert calls[1].kwargs == {"p": "?"}
    assert len(parse_calls(data, targets, [FIXES], limit=1)) == 1


def test_parse_calls_rejects_bad_shape() -> None:
    with pytest.raises(LLMError):
        parse_calls({"calls": "x"}, [], [])


def test_parse_results_ignores_noise() -> None:
    out = (
        'noise\n{"i": 0, "ok": true, "value": "1"}\n{broken\n{"i": "x"}\n'
        '{"i": 1, "ok": false, "exc": "E", "msg": ""}\n[1]\n'
    )
    assert sorted(parse_results(out)) == [0, 1]


def test_no_behavior_change_refuted_when_outputs_differ(tmp_path: Path, make_runner) -> None:
    ctx = _ctx(tmp_path)
    runner = make_runner(_handler(_ok(0, "'Hello, Ann!'"), [_ok(0, "'Hello, Ann.'")]))
    result = Characterizer(_llm(_call("Ann")), runner).run(ctx, [NO_CHANGE], RANGES)

    assert [r.status for r in result.claim_results] == [ClaimStatus.REFUTED]
    assert result.claim_results[0].command_indexes == [0, 1]
    high = [f for f in result.findings if f.severity is Severity.HIGH]
    assert high[0].title == "Claim refuted: no change"
    assert "Ann" in high[0].detail
    assert len(ctx.evidence.commands) == 3
    assert not (ctx.base_dir / CHAR_DIR).exists()
    assert not (ctx.head_dir / CHAR_DIR).exists()


def test_identical_outputs_do_not_refute(tmp_path: Path, make_runner) -> None:
    ctx = _ctx(tmp_path)
    same = _ok(0, "'Hello, Ann!'")
    runner = make_runner(_handler(same, [same]))
    result = Characterizer(_llm(_call("Ann")), runner).run(ctx, [NO_CHANGE], RANGES)

    assert result.claim_results == []
    assert [f.severity for f in result.findings] == [Severity.INFO]
    assert "1 input(s) compared, 0 differ" in result.findings[0].title


def test_nondeterministic_calls_are_dropped(tmp_path: Path, make_runner) -> None:
    ctx = _ctx(tmp_path)
    runner = make_runner(_handler(_ok(0, "1"), [_ok(0, "2"), _ok(0, "3")]))
    result = Characterizer(_llm(_call("Ann")), runner).run(ctx, [NO_CHANGE], RANGES)

    assert result.claim_results == []
    assert "0 input(s) compared" in result.findings[0].title


def test_fix_still_crashing_is_refuted(tmp_path: Path, make_runner) -> None:
    ctx = _ctx(tmp_path)
    runner = make_runner(_handler(_exc(0, "IndexError"), [_exc(0, "IndexError")]))
    result = Characterizer(_llm(_call(claim="c1")), runner).run(ctx, [FIXES], RANGES)

    assert [r.status for r in result.claim_results] == [ClaimStatus.REFUTED]
    assert "still fails" in result.claim_results[0].explanation


def test_effective_fix_is_not_refuted(tmp_path: Path, make_runner) -> None:
    ctx = _ctx(tmp_path)
    runner = make_runner(_handler(_exc(0, "IndexError"), [_ok(0, "None")]))
    result = Characterizer(_llm(_call(claim="c1")), runner).run(ctx, [FIXES], RANGES)
    assert result.claim_results == []


def test_untargeted_fix_is_not_refuted(tmp_path: Path, make_runner) -> None:
    ctx = _ctx(tmp_path)
    runner = make_runner(_handler(_exc(0, "IndexError"), [_exc(0, "IndexError")]))
    result = Characterizer(_llm(_call()), runner).run(ctx, [FIXES], RANGES)
    assert result.claim_results == []


def test_skipped_without_relevant_claims(tmp_path: Path, make_runner) -> None:
    ctx = _ctx(tmp_path)
    llm = ScriptedLLM([])
    other = Claim(id="c1", text="nicer", kind=ClaimKind.OTHER)
    runner = make_runner(_handler("", [""]))
    result = Characterizer(llm, runner).run(ctx, [other], RANGES)

    assert result.findings == []
    assert result.claim_results == []
    assert llm.calls == []
    assert runner.calls == []


def test_no_changed_functions(tmp_path: Path, make_runner) -> None:
    ctx = _ctx(tmp_path)
    runner = make_runner(_handler("", [""]))
    result = Characterizer(ScriptedLLM([]), runner).run(ctx, [NO_CHANGE], {"README.md": [(1, 1)]})

    assert [f.severity for f in result.findings] == [Severity.INFO]
    assert runner.calls == []


def test_generation_failure_is_low(tmp_path: Path, make_runner) -> None:
    ctx = _ctx(tmp_path)
    runner = make_runner(_handler("", [""]))
    result = Characterizer(ScriptedLLM(["junk"]), runner).run(ctx, [NO_CHANGE], RANGES)

    assert [f.severity for f in result.findings] == [Severity.LOW]
    assert runner.calls == []


def test_driver_failure_is_low(tmp_path: Path, make_runner) -> None:
    ctx = _ctx(tmp_path)
    runner = make_runner(lambda workdir, argv: (127, "", "no python"))
    result = Characterizer(_llm(_call("Ann")), runner).run(ctx, [NO_CHANGE], RANGES)

    assert [f.severity for f in result.findings] == [Severity.LOW]
    assert "could not run" in result.findings[0].title
    assert result.claim_results == []
    assert not (ctx.head_dir / CHAR_DIR).exists()


def test_import_failures_are_not_evidence(tmp_path: Path, make_runner) -> None:
    ctx = _ctx(tmp_path)
    same = _exc(0, "ModuleNotFoundError")
    runner = make_runner(_handler(same, [same]))
    result = Characterizer(_llm(_call("Ann")), runner).run(ctx, [NO_CHANGE], RANGES)

    assert result.claim_results == []
    assert "could not import" in result.findings[0].title


def test_merge_replaces_result_and_drops_stale_finding() -> None:
    audit = AgentResult(
        findings=[Finding(source="auditor", title="Claim not verified: no change", severity=Severity.LOW)],
        claim_results=[
            ClaimResult(claim_id="c1", status=ClaimStatus.UNVERIFIABLE, command_indexes=[0])
        ],
    )
    char = AgentResult(
        findings=[
            Finding(source="characterize", title="Claim refuted: no change", severity=Severity.HIGH),
            Finding(source="characterize", title="Differential check: 1 input(s) compared, 1 differ", severity=Severity.INFO),
        ],
        claim_results=[
            ClaimResult(claim_id="c1", status=ClaimStatus.REFUTED, command_indexes=[5, 6])
        ],
    )
    merge_characterization(audit, char, [NO_CHANGE])

    assert [r.status for r in audit.claim_results] == [ClaimStatus.REFUTED]
    assert audit.claim_results[0].command_indexes == [0, 5, 6]
    assert [f.title for f in audit.findings] == [
        "Claim refuted: no change",
        "Differential check: 1 input(s) compared, 1 differ",
    ]


def test_merge_keeps_existing_refutation_without_duplicates() -> None:
    audit = AgentResult(
        findings=[Finding(source="auditor", title="Claim refuted: no change", severity=Severity.HIGH)],
        claim_results=[
            ClaimResult(claim_id="c1", status=ClaimStatus.REFUTED, command_indexes=[0, 1])
        ],
    )
    char = AgentResult(
        findings=[Finding(source="characterize", title="Claim refuted: no change", severity=Severity.HIGH)],
        claim_results=[
            ClaimResult(claim_id="c1", status=ClaimStatus.REFUTED, command_indexes=[7, 8])
        ],
    )
    merge_characterization(audit, char, [NO_CHANGE])

    assert audit.claim_results[0].command_indexes == [0, 1]
    assert len(audit.findings) == 1


@pytest.mark.docker
@needs_docker
def test_driver_runs_in_sandbox(tmp_path: Path) -> None:
    (tmp_path / "greet.py").write_text(HEAD_SRC)
    directory = tmp_path / CHAR_DIR
    directory.mkdir()
    (directory / "__init__.py").write_text("")
    (directory / "driver.py").write_text(DRIVER)
    calls = [
        {"module": "greet", "function": "greet", "args": ["Ann"], "kwargs": {}},
        {"module": "greet", "function": "greet", "args": [], "kwargs": {}},
        {"module": "nope", "function": "x", "args": [], "kwargs": {}},
    ]
    (directory / "calls.json").write_text(json.dumps(calls))

    runner = SandboxRunner(SandboxPolicy(image="python:3.12-slim", timeout_s=60))
    runner.ensure_image()
    record = runner.run(tmp_path, ARGV)
    results = parse_results(record.stdout)

    assert results[0] == {"i": 0, "ok": True, "value": "'Hello, Ann.'"}
    assert results[1]["exc"] == "TypeError"
    assert results[2]["exc"] == "ModuleNotFoundError"
