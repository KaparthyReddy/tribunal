from collections.abc import Callable
from pathlib import Path

from tribunal.agents import AuditContext, Evidence, FailToPass
from tribunal.models import Claim, ClaimKind, ClaimStatus, Submission

ARGV = ["python", "-m", "unittest"]
FIX = Claim(id="c1", text="fixes the crash", kind=ClaimKind.FIXES)
OLD = "old test\n"
NEW = "new test\n"


def _ctx(tmp_path: Path, test_command: list[str] | None = None) -> AuditContext:
    base, head = tmp_path / "base", tmp_path / "head"
    for root, test in ((base, OLD), (head, NEW)):
        root.mkdir(parents=True)
        (root / "test_x.py").write_text(test)
        (root / "x.py").write_text("x = 1\n")
    submission = Submission(
        repo="o/r",
        repo_path=str(tmp_path),
        base_sha="a" * 40,
        head_sha="b" * 40,
        title="t",
        test_command=ARGV if test_command is None else test_command,
    )
    evidence = Evidence(sides={base: "base", head: "head"})
    return AuditContext(submission=submission, base_dir=base, head_dir=head, evidence=evidence)


def _handler(
    base_new_exit: int = 1, base_new_out: str = "AssertionError", base_old_exit: int = 0
) -> Callable[[Path, list[str]], tuple[int, str, str]]:
    def handler(workdir: Path, argv: list[str]) -> tuple[int, str, str]:
        if workdir.name == "head":
            return 0, "ok", ""
        if "new test" in (workdir / "test_x.py").read_text():
            return base_new_exit, "", base_new_out
        return base_old_exit, "ok", ""

    return handler


def _prime(ctx: AuditContext, runner) -> None:
    ctx.evidence.run(runner, ctx.base_dir, ARGV)
    ctx.evidence.run(runner, ctx.head_dir, ARGV)


def test_added_test_that_fails_on_base_supports_the_fix(tmp_path: Path, make_runner) -> None:
    ctx = _ctx(tmp_path)
    runner = make_runner(_handler())
    _prime(ctx, runner)

    result = FailToPass(runner).run(ctx, [FIX], ["x.py", "test_x.py"])

    assert [(r.claim_id, r.status) for r in result.claim_results] == [("c1", ClaimStatus.SUPPORTED)]
    assert result.claim_results[0].command_indexes == [2, 1]
    assert ctx.evidence.commands[2].side == "base"
    assert ctx.evidence.commands[2].overlay
    assert (ctx.base_dir / "test_x.py").read_text() == OLD


def test_a_test_that_passes_on_base_proves_nothing(tmp_path: Path, make_runner) -> None:
    ctx = _ctx(tmp_path)
    runner = make_runner(_handler(base_new_exit=0))
    _prime(ctx, runner)
    result = FailToPass(runner).run(ctx, [FIX], ["x.py", "test_x.py"])
    assert result.claim_results == []
    assert result.findings == []


def test_an_import_failure_is_not_accepted(tmp_path: Path, make_runner) -> None:
    ctx = _ctx(tmp_path)
    runner = make_runner(_handler(base_new_out="ModuleNotFoundError: No module named 'x'"))
    _prime(ctx, runner)
    result = FailToPass(runner).run(ctx, [FIX], ["x.py", "test_x.py"])
    assert result.claim_results == []
    assert "import error" in result.findings[0].title


def test_several_fix_claims_cannot_share_one_test(tmp_path: Path, make_runner) -> None:
    ctx = _ctx(tmp_path)
    runner = make_runner(_handler())
    _prime(ctx, runner)
    other = Claim(id="c2", text="also fixes", kind=ClaimKind.FIXES)
    result = FailToPass(runner).run(ctx, [FIX, other], ["x.py", "test_x.py"])
    assert result.claim_results == []
    assert result.findings[0].title.startswith("A changed test fails on base and passes on head")


def test_nothing_runs_when_the_base_suite_already_fails(tmp_path: Path, make_runner) -> None:
    ctx = _ctx(tmp_path)
    runner = make_runner(_handler(base_old_exit=1))
    _prime(ctx, runner)
    result = FailToPass(runner).run(ctx, [FIX], ["x.py", "test_x.py"])
    assert result.claim_results == []
    assert len(ctx.evidence.commands) == 2


def test_nothing_runs_without_changed_tests_or_a_test_command(tmp_path: Path, make_runner) -> None:
    ctx = _ctx(tmp_path)
    runner = make_runner(_handler())
    _prime(ctx, runner)
    assert FailToPass(runner).run(ctx, [FIX], ["x.py"]).claim_results == []
    assert len(ctx.evidence.commands) == 2

    bare = _ctx(tmp_path / "bare", test_command=[])
    assert FailToPass(runner).run(bare, [FIX], ["test_x.py"]).claim_results == []
