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
    analyze_changes,
    module_name,
    parse_calls,
    parse_results,
    parse_trace,
)
from tribunal.graph import FileChange
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
CHANGES = {"greet.py": FileChange(added=((1, 2),), removed=((1, 2),))}
COVERED = {"greet.py": [1, 2]}
NO_CHANGE = Claim(id="c1", text="no change", kind=ClaimKind.NO_BEHAVIOR_CHANGE)
FIXES = Claim(id="c1", text="fixes the crash", kind=ClaimKind.FIXES)
BAD = json.dumps({"calls": [{"module": "other", "function": "x", "args": [], "kwargs": {}}]})
KEEP = "def keep():\n    return 1\n"

needs_docker = pytest.mark.skipif(not docker_available(), reason="docker unavailable")


def _ctx(
    tmp_path: Path, base_src: str = BASE_SRC, head_src: str = HEAD_SRC, name: str = "greet.py"
) -> AuditContext:
    base, head = tmp_path / "base", tmp_path / "head"
    for root, source in ((base, base_src), (head, head_src)):
        root.mkdir()
        (root / name).write_text(source)
    submission = Submission(
        repo="o/r", repo_path=str(tmp_path), base_sha="a" * 40, head_sha="b" * 40, title="t"
    )
    return AuditContext(
        submission=submission, base_dir=base, head_dir=head, evidence=Evidence(), diff="diff"
    )


def _call(*args, claim: str | None = None) -> dict:
    return {
        "module": "greet",
        "function": "greet",
        "args": list(args),
        "kwargs": {},
        "claim": claim,
    }


def _llm(*batches: list[dict]) -> ScriptedLLM:
    return ScriptedLLM([json.dumps({"calls": batch}) for batch in batches])


def _result(index: int, value: str = "'Hello, Ann!'", state: str = "[['Ann'], {}]") -> dict:
    return {"i": index, "ok": True, "value": value, "state": state}


def _raised(index: int, exc: str, msg: str = "") -> dict:
    return {"i": index, "ok": False, "exc": exc, "msg": msg, "state": "[[], {}]"}


def _out(results: list[dict], trace: dict | None = None) -> str:
    lines = [json.dumps(item) for item in results]
    if trace is not None:
        lines.append(json.dumps({"trace": trace}))
    return "\n".join(lines)


def _runner(make_runner, base_out: str, head_out: str):
    def handler(workdir: Path, argv: list[str]) -> tuple[int, str, str]:
        return 0, (base_out if workdir.name == "base" else head_out), ""

    return make_runner(handler)


def _run(ctx, llm, runner, claims, changed_files=("greet.py",), changes=CHANGES) -> AgentResult:
    return Characterizer(llm, runner).run(ctx, claims, changes, list(changed_files))


def _write(root: Path, files: dict[str, str]) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    for name, text in files.items():
        (root / name).write_text(text)
    return root


def _analyze(tmp_path: Path, base: dict[str, str], head: dict[str, str], changes):
    return analyze_changes(
        _write(tmp_path / "base", base), _write(tmp_path / "head", head), changes
    )


def test_module_name() -> None:
    assert module_name("pkg/mod.py") == "pkg.mod"
    assert module_name("pkg/__init__.py") == "pkg"
    assert module_name("top.py") == "top"
    assert module_name("my-dir/x.py") is None
    assert module_name("README.md") is None
    assert module_name("__init__.py") is None


def test_parse_calls_filters() -> None:
    targets = [Target("greet.py", "greet", "greet", "")]
    data = {
        "calls": [
            _call("a", claim="c1"),
            _call("a"),
            {"module": "greet", "function": "other", "args": []},
            {"module": "greet", "function": "greet", "args": "bad"},
            {
                "module": "greet",
                "function": "greet",
                "args": [],
                "kwargs": {"p": "?"},
                "claim": "c9",
            },
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


def test_parse_results_and_trace_ignore_noise() -> None:
    out = (
        'noise\n{"i": 0, "ok": true, "value": "1"}\n{broken\n{"i": "x"}\n'
        '{"trace": {"a.py": [1, 2, "x"], "b.py": "bad"}}\n'
    )
    assert sorted(parse_results(out)) == [0]
    assert parse_trace(out) == {"a.py": {1, 2}}
    assert parse_trace("nothing") is None


def test_analysis_targets_a_changed_top_level_function(tmp_path: Path) -> None:
    analysis = _analyze(tmp_path, {"greet.py": BASE_SRC}, {"greet.py": HEAD_SRC}, CHANGES)
    assert [(t.module, t.function) for t in analysis.targets] == [("greet", "greet")]
    assert analysis.head_required == {"greet.py": {1, 2}}
    assert analysis.base_required == {"greet.py": {1, 2}}
    assert analysis.outside == []


def test_analysis_leaves_methods_outside_its_reach(tmp_path: Path) -> None:
    base = "class A:\n    def m(self):\n        return 1\n"
    head = base.replace("return 1", "return 2")
    change = {"a.py": FileChange(added=((3, 3),), removed=((3, 3),))}
    analysis = _analyze(tmp_path, {"a.py": base}, {"a.py": head}, change)
    assert analysis.targets == []
    assert analysis.outside == ["A.m (a.py)"]


def test_analysis_module_level_change_targets_every_function(tmp_path: Path) -> None:
    base = "MAX = 3\n\n\ndef ok(n):\n    return n < MAX\n"
    head = base.replace("MAX = 3", "MAX = 2")
    change = {"retry.py": FileChange(added=((1, 1),), removed=((1, 1),))}
    analysis = _analyze(tmp_path, {"retry.py": base}, {"retry.py": head}, change)
    assert [(t.module, t.function) for t in analysis.targets] == [("retry", "ok")]
    assert analysis.head_required == {"retry.py": {1}}
    assert analysis.base_required == {"retry.py": {1}}


def test_analysis_class_body_is_outside_its_reach(tmp_path: Path) -> None:
    change = {"k.py": FileChange(added=((2, 2),), removed=((2, 2),))}
    analysis = _analyze(
        tmp_path, {"k.py": "class K:\n    x = 1\n"}, {"k.py": "class K:\n    x = 2\n"}, change
    )
    assert analysis.targets == []
    assert analysis.outside == ["class body in k.py"]


def test_analysis_removed_functions_depend_on_whether_they_are_referenced(tmp_path: Path) -> None:
    base = "def total(xs):\n    return sum(xs)\n\n\ndef _legacy(xs):\n    return 0\n"
    change = {"totals.py": FileChange(removed=((3, 6),))}

    unused = _analyze(tmp_path / "a", {"totals.py": base}, {"totals.py": base[:41]}, change)
    assert unused.deleted_functions == ["_legacy"]
    assert unused.outside == []

    caller = "def total(xs):\n    return sum(xs)\n\n\ndef other():\n    return _legacy([1])\n"
    used = _analyze(tmp_path / "b", {"totals.py": base}, {"totals.py": caller}, change)
    assert "removed function _legacy is still referenced" in used.outside


def test_a_difference_refutes_a_no_change_claim(tmp_path: Path, make_runner) -> None:
    ctx = _ctx(tmp_path)
    runner = _runner(
        make_runner, _out([_result(0)], COVERED), _out([_result(0, "'Hello, Ann.'")], COVERED)
    )
    result = _run(ctx, _llm([_call("Ann")]), runner, [NO_CHANGE])

    assert [r.status for r in result.claim_results] == [ClaimStatus.REFUTED]
    assert result.claim_results[0].command_indexes == [0, 1]
    high = [f for f in result.findings if f.severity is Severity.HIGH]
    assert high[0].title == "Claim refuted: no change"
    assert "Ann" in high[0].detail
    assert not result.behavior_identical
    assert len(ctx.evidence.commands) == 3
    assert not (ctx.base_dir / CHAR_DIR).exists()
    assert not (ctx.head_dir / CHAR_DIR).exists()


def test_identical_covered_inputs_support_a_no_change_claim(tmp_path: Path, make_runner) -> None:
    same = _out([_result(0)], COVERED)
    result = _run(
        _ctx(tmp_path), _llm([_call("Ann")]), _runner(make_runner, same, same), [NO_CHANGE]
    )

    assert [r.status for r in result.claim_results] == [ClaimStatus.SUPPORTED]
    assert result.behavior_identical
    assert [f.severity for f in result.findings] == [Severity.INFO]
    assert "1 input(s) compared, 0 differ" in result.findings[0].title


def test_unexecuted_changed_lines_block_support(tmp_path: Path, make_runner) -> None:
    partial = _out([_result(0)], {"greet.py": [2]})
    llm = _llm([_call("Ann")])
    result = _run(_ctx(tmp_path), llm, _runner(make_runner, partial, partial), [NO_CHANGE])

    assert result.claim_results == []
    assert not result.behavior_identical
    flagged = [f for f in result.findings if f.severity is Severity.MEDIUM]
    assert flagged[0].title == "Changed code never exercised by the differential inputs"
    assert "greet.py:1" in flagged[0].detail
    assert len(llm.calls) == 2


def test_a_second_round_of_inputs_can_complete_coverage(tmp_path: Path, make_runner) -> None:
    holder: dict = {}

    def handler(workdir: Path, argv: list[str]) -> tuple[int, str, str]:
        if len(holder["runner"].calls) <= 3:
            return 0, _out([_result(0)], {"greet.py": [2]}), ""
        both = [_result(0), _result(1, "'Hello, Bob!'", "[['Bob'], {}]")]
        return 0, _out(both, COVERED), ""

    holder["runner"] = make_runner(handler)
    llm = _llm([_call("Ann")], [_call("Bob")])
    ctx = _ctx(tmp_path)
    result = _run(ctx, llm, holder["runner"], [NO_CHANGE])

    assert [r.status for r in result.claim_results] == [ClaimStatus.SUPPORTED]
    assert len(llm.calls) == 2
    assert "greet.py:1" in llm.calls[1][1]
    assert len(ctx.evidence.commands) == 6
    assert not [f for f in result.findings if f.severity is Severity.MEDIUM]


@pytest.mark.parametrize(
    ("changed_files", "severity", "title"),
    [
        (["greet.py"], Severity.MEDIUM, "Behavior change not declared: 1 input(s) differ"),
        (["greet.py", "test_greet.py"], Severity.INFO, "Behavior differs on 1 input(s)"),
    ],
)
def test_an_undeclared_difference_needs_review_unless_tests_changed(
    tmp_path: Path, make_runner, changed_files, severity, title
) -> None:
    runner = _runner(
        make_runner, _out([_result(0)], COVERED), _out([_result(0, "'Hello, Ann.'")], COVERED)
    )
    result = _run(_ctx(tmp_path), _llm([_call("Ann")]), runner, [], changed_files)

    assert result.claim_results == []
    assert [f.severity for f in result.findings if f.title == title] == [severity]


def test_a_targeted_input_that_stops_raising_supports_a_fix(tmp_path: Path, make_runner) -> None:
    runner = _runner(
        make_runner,
        _out([_raised(0, "IndexError")], COVERED),
        _out([_result(0, "None", "[[], {}]")], COVERED),
    )
    result = _run(_ctx(tmp_path), _llm([_call(claim="c1")]), runner, [FIXES])

    assert [(r.claim_id, r.status) for r in result.claim_results] == [("c1", ClaimStatus.SUPPORTED)]
    assert "now succeeds" in result.claim_results[0].explanation


def test_a_targeted_input_that_still_fails_refutes_a_fix(tmp_path: Path, make_runner) -> None:
    same = _out([_raised(0, "IndexError")], COVERED)
    result = _run(
        _ctx(tmp_path), _llm([_call(claim="c1")]), _runner(make_runner, same, same), [FIXES]
    )
    assert [r.status for r in result.claim_results] == [ClaimStatus.REFUTED]
    assert "still fails" in result.claim_results[0].explanation


def test_calls_that_need_the_new_signature_are_not_compared(tmp_path: Path, make_runner) -> None:
    base_out = _out(
        [_raised(0, "TypeError", "greet() got an unexpected keyword argument 'x'")], COVERED
    )
    head_out = _out([_result(0)], COVERED)
    result = _run(
        _ctx(tmp_path), _llm([_call("Ann")]), _runner(make_runner, base_out, head_out), [NO_CHANGE]
    )

    assert result.claim_results == []
    assert "0 input(s) compared, 0 differ" in result.findings[0].title
    assert "new version" in result.findings[0].detail


def test_argument_state_is_part_of_the_comparison(tmp_path: Path, make_runner) -> None:
    runner = _runner(
        make_runner,
        _out([_result(0, "[1, 2, 3]", "[[3, 1, 2], {}]")], COVERED),
        _out([_result(0, "[1, 2, 3]", "[[1, 2, 3], {}]")], COVERED),
    )
    result = _run(_ctx(tmp_path), _llm([_call("Ann")]), runner, [NO_CHANGE])

    assert [r.status for r in result.claim_results] == [ClaimStatus.REFUTED]
    assert "leaves its arguments as" in result.claim_results[0].explanation


def test_nondeterministic_inputs_are_dropped(tmp_path: Path, make_runner) -> None:
    holder: dict = {}

    def handler(workdir: Path, argv: list[str]) -> tuple[int, str, str]:
        if workdir.name == "base":
            return 0, _out([_result(0)], COVERED), ""
        value = "'a'" if len(holder["runner"].calls) == 2 else "'b'"
        return 0, _out([_result(0, value)], COVERED), ""

    holder["runner"] = make_runner(handler)
    result = _run(_ctx(tmp_path), _llm([_call("Ann")]), holder["runner"], [NO_CHANGE])

    assert result.claim_results == []
    assert "0 input(s) compared, 0 differ" in result.findings[0].title


def test_syntactically_identical_code_is_settled_statically(tmp_path: Path, make_runner) -> None:
    head = 'def greet(name, punct="!"):\n    """Greet."""\n    # say hello\n    return "Hello, " + name + punct\n'
    llm = ScriptedLLM([])
    runner = make_runner(lambda workdir, argv: (0, "", ""))
    result = _run(_ctx(tmp_path, BASE_SRC, head), llm, runner, [NO_CHANGE])

    assert [r.status for r in result.claim_results] == [ClaimStatus.SUPPORTED]
    assert result.behavior_identical
    assert result.findings[0].title == "Static check: no runtime change"
    assert llm.calls == []
    assert runner.calls == []


@pytest.mark.parametrize(
    ("base", "head", "change", "identical"),
    [
        (KEEP, KEEP + "\n\ndef added():\n    return 2\n", FileChange(added=((3, 6),)), False),
        (KEEP + "\n\ndef old():\n    return 2\n", KEEP, FileChange(removed=((3, 6),)), True),
    ],
)
def test_structural_changes_leave_existing_behavior_unchanged(
    tmp_path: Path, make_runner, base, head, change, identical
) -> None:
    llm = ScriptedLLM([])
    runner = make_runner(lambda workdir, argv: (0, "", ""))
    result = _run(
        _ctx(tmp_path, base, head, "m.py"), llm, runner, [NO_CHANGE], ["m.py"], {"m.py": change}
    )

    assert [r.status for r in result.claim_results] == [ClaimStatus.SUPPORTED]
    assert result.behavior_identical is identical
    assert result.findings[0].title == "Structural check: no existing function changed"
    assert llm.calls == []


def test_changes_outside_the_reach_are_reported_not_called(tmp_path: Path, make_runner) -> None:
    base = "class A:\n    def m(self):\n        return 1\n"
    head = base.replace("return 1", "return 2")
    change = {"a.py": FileChange(added=((3, 3),), removed=((3, 3),))}
    llm = ScriptedLLM([])
    runner = make_runner(lambda workdir, argv: (0, "", ""))
    result = _run(_ctx(tmp_path, base, head, "a.py"), llm, runner, [NO_CHANGE], ["a.py"], change)

    assert result.claim_results == []
    assert [(f.severity, f.title) for f in result.findings] == [
        (Severity.INFO, "Differential check skipped: changed code is outside its reach")
    ]
    assert llm.calls == []


def test_unusable_inputs_get_one_repair_attempt(tmp_path: Path, make_runner) -> None:
    same = _out([_result(0)], COVERED)
    llm = ScriptedLLM([BAD, json.dumps({"calls": [_call("Ann")]})])
    result = _run(_ctx(tmp_path), llm, _runner(make_runner, same, same), [NO_CHANGE])

    assert [r.status for r in result.claim_results] == [ClaimStatus.SUPPORTED]
    assert len(llm.calls) == 2
    assert "rejected" in llm.calls[1][1]


def test_inputs_that_stay_unusable_skip_the_check(tmp_path: Path, make_runner) -> None:
    runner = make_runner(lambda workdir, argv: (0, "", ""))
    result = _run(_ctx(tmp_path), ScriptedLLM([BAD, BAD]), runner, [NO_CHANGE])

    assert [(f.severity, f.title) for f in result.findings] == [
        (Severity.LOW, "Differential check skipped: input generation failed")
    ]
    assert runner.calls == []


def test_a_driver_that_cannot_run_is_reported(tmp_path: Path, make_runner) -> None:
    ctx = _ctx(tmp_path)
    runner = make_runner(lambda workdir, argv: (127, "", "no python"))
    result = _run(ctx, _llm([_call("Ann")]), runner, [NO_CHANGE])

    assert [(f.severity, f.title) for f in result.findings] == [
        (Severity.LOW, "Differential check could not run")
    ]
    assert result.claim_results == []
    assert not (ctx.head_dir / CHAR_DIR).exists()


def test_import_failures_are_not_evidence(tmp_path: Path, make_runner) -> None:
    same = _out([_raised(0, "ModuleNotFoundError")], COVERED)
    result = _run(
        _ctx(tmp_path), _llm([_call("Ann")]), _runner(make_runner, same, same), [NO_CHANGE]
    )
    assert result.claim_results == []
    assert "could not import" in result.findings[0].title


def test_merge_replaces_result_and_drops_stale_finding() -> None:
    audit = AgentResult(
        findings=[
            Finding(source="auditor", title="Claim not verified: no change", severity=Severity.LOW)
        ],
        claim_results=[
            ClaimResult(claim_id="c1", status=ClaimStatus.UNVERIFIABLE, command_indexes=[0])
        ],
    )
    extra = AgentResult(
        findings=[
            Finding(
                source="characterize", title="Claim refuted: no change", severity=Severity.HIGH
            ),
            Finding(
                source="characterize",
                title="Differential check: 1 input(s) compared, 1 differ",
                severity=Severity.INFO,
            ),
        ],
        claim_results=[
            ClaimResult(claim_id="c1", status=ClaimStatus.REFUTED, command_indexes=[5, 6])
        ],
    )
    merge_characterization(audit, extra, [NO_CHANGE])

    assert [r.status for r in audit.claim_results] == [ClaimStatus.REFUTED]
    assert audit.claim_results[0].command_indexes == [0, 5, 6]
    assert [f.title for f in audit.findings] == [
        "Claim refuted: no change",
        "Differential check: 1 input(s) compared, 1 differ",
    ]


def test_merge_keeps_an_existing_refutation_without_duplicates() -> None:
    audit = AgentResult(
        findings=[
            Finding(source="auditor", title="Claim refuted: no change", severity=Severity.HIGH)
        ],
        claim_results=[
            ClaimResult(claim_id="c1", status=ClaimStatus.REFUTED, command_indexes=[0, 1])
        ],
    )
    extra = AgentResult(
        findings=[
            Finding(source="characterize", title="Claim refuted: no change", severity=Severity.HIGH)
        ],
        claim_results=[
            ClaimResult(claim_id="c1", status=ClaimStatus.REFUTED, command_indexes=[7, 8])
        ],
    )
    merge_characterization(audit, extra, [NO_CHANGE])

    assert audit.claim_results[0].command_indexes == [0, 1]
    assert len(audit.findings) == 1


@pytest.mark.docker
@needs_docker
def test_driver_traces_and_compares_state_in_the_sandbox(tmp_path: Path) -> None:
    (tmp_path / "greet.py").write_text(HEAD_SRC)
    (tmp_path / "lst.py").write_text("def srt(xs):\n    xs.sort()\n    return xs\n")
    directory = tmp_path / CHAR_DIR
    directory.mkdir()
    (directory / "__init__.py").write_text("")
    (directory / "driver.py").write_text(DRIVER)
    calls = [
        {"module": "greet", "function": "greet", "args": ["Ann"], "kwargs": {}},
        {"module": "greet", "function": "greet", "args": [], "kwargs": {}},
        {"module": "lst", "function": "srt", "args": [[3, 1, 2]], "kwargs": {}},
        {"module": "nope", "function": "x", "args": [], "kwargs": {}},
    ]
    spec = {"calls": calls, "trace": ["greet.py", "lst.py"]}
    (directory / "calls.json").write_text(json.dumps(spec))

    runner = SandboxRunner(SandboxPolicy(image="python:3.12-slim", timeout_s=60))
    runner.ensure_image()
    record = runner.run(tmp_path, ARGV)
    results = parse_results(record.stdout)
    trace = parse_trace(record.stdout)

    assert results[0] == {"i": 0, "ok": True, "value": "'Hello, Ann.'", "state": "[['Ann'], {}]"}
    assert results[1]["exc"] == "TypeError"
    assert results[2]["value"] == "[1, 2, 3]"
    assert results[2]["state"] == "[[[1, 2, 3]], {}]"
    assert results[3]["exc"] == "ModuleNotFoundError"
    assert trace is not None
    assert {1, 2} <= trace["greet.py"]
    assert {1, 2, 3} <= trace["lst.py"]
