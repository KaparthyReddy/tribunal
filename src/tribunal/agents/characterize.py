import json
import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any

from tribunal.agents.auditor import AuditContext
from tribunal.agents.base import CRITICAL_KINDS, AgentResult, CommandRunner, is_infra_failure
from tribunal.agents.staticcheck import class_spans, required_line, same_syntax, statement_spans
from tribunal.graph import CallGraph, FileChange, Symbol, build_callgraph, is_test_file
from tribunal.llm import LLMClient, LLMError, complete_parsed
from tribunal.models import Claim, ClaimKind, ClaimResult, ClaimStatus, Finding, Severity

CHAR_DIR = "tribunal_chars"
ARGV = ["python", "-m", f"{CHAR_DIR}.driver"]
MAX_CALLS = 24
MAX_TOTAL_CALLS = 36
MAX_FUNCTIONS = 8
MAX_SOURCE_CHARS = 1500
MAX_DIFF_CHARS = 8000
MAX_CALL_CHARS = 2000
MAX_LINES_PER_RANGE = 2000
MAX_UNCOVERED_SHOWN = 12
IMPORT_ERRORS = frozenset({"ModuleNotFoundError", "ImportError"})
SIGNATURE_ERROR = re.compile(
    r"unexpected keyword argument|positional argument|required positional|takes \d+ positional"
)
DOC_SUFFIXES = (".md", ".rst")

DRIVER = """\
import contextlib
import copy
import importlib
import io
import json
import os
import signal
import sys

CALL_TIMEOUT_S = 5


class _Timeout(Exception):
    pass


def _on_alarm(signum, frame):
    raise _Timeout()


def _describe(value):
    text = repr(value)
    return text if len(text) <= 500 else text[:500] + "..."


def main():
    with open("tribunal_chars/calls.json", encoding="utf-8") as handle:
        spec = json.load(handle)
    calls = spec["calls"]
    watch = set(spec.get("trace", []))
    executed = {}
    names = {}

    def watched(filename):
        if filename not in names:
            try:
                rel = os.path.relpath(os.path.abspath(filename), os.getcwd()).replace(os.sep, "/")
            except ValueError:
                rel = ""
            names[filename] = rel if rel in watch else ""
        return names[filename]

    def tracer(frame, event, arg):
        rel = watched(frame.f_code.co_filename)
        if not rel:
            return None
        lines = executed.setdefault(rel, set())

        def local(frame, event, arg):
            if event == "line":
                lines.add(frame.f_lineno)
            return local

        return local

    signal.signal(signal.SIGALRM, _on_alarm)
    if watch:
        sys.settrace(tracer)
    try:
        for index, call in enumerate(calls):
            signal.alarm(CALL_TIMEOUT_S)
            args = copy.deepcopy(call["args"])
            kwargs = copy.deepcopy(call["kwargs"])
            try:
                module = importlib.import_module(call["module"])
                function = getattr(module, call["function"])
                with contextlib.redirect_stdout(io.StringIO()):
                    value = function(*args, **kwargs)
                record = {"i": index, "ok": True, "value": _describe(value)}
            except _Timeout:
                record = {"i": index, "ok": False, "exc": "Timeout", "msg": ""}
            except BaseException as exc:
                record = {"i": index, "ok": False, "exc": type(exc).__name__, "msg": str(exc)[:200]}
            finally:
                signal.alarm(0)
            record["state"] = _describe([args, kwargs])
            print(json.dumps(record), flush=True)
    finally:
        sys.settrace(None)
    trace = {name: sorted(lines) for name, lines in executed.items()}
    print(json.dumps({"trace": trace}), flush=True)


main()
"""

SYSTEM = """You design test inputs for comparing two versions of the same Python functions.
A coding agent changed the functions below. Your calls will run on the old and the new version,
and the results and the state of the arguments afterwards will be compared, so choose inputs
that would expose any difference in behavior.
Rules:
- Only call the listed functions, using the exact module and function names given.
- args is a JSON array and kwargs is a JSON object. Use JSON values only.
- Return at most {n} calls in total.
- Make sure the calls reach every branch of the changed code, including error paths.
- Cover typical values, empty inputs, None, zero, negatives, values on both sides of every
  comparison, duplicates, ties, unordered input, mixed case, padded whitespace, punctuation,
  unicode and invalid values.
- Include calls that omit optional arguments so default values are exercised.
- Include calls that pass mutable arguments such as lists and dicts.
- For every claim of kind fixes, include the exact input the claim describes and set "claim"
  to that claim's id. Use null for all other calls.
- Never include calls that depend on time, randomness, files or the network.
Output JSON only, no prose:
{"calls": [{"module": "...", "function": "...", "args": [], "kwargs": {}, "claim": null}]}"""


@dataclass(frozen=True)
class Target:
    file: str
    module: str
    function: str
    source: str


@dataclass(frozen=True)
class Call:
    module: str
    function: str
    args: list[Any]
    kwargs: dict[str, Any]
    claim: str | None = None


@dataclass
class Analysis:
    targets: list[Target] = field(default_factory=list)
    head_required: dict[str, set[int]] = field(default_factory=dict)
    base_required: dict[str, set[int]] = field(default_factory=dict)
    outside: list[str] = field(default_factory=list)
    new_functions: list[str] = field(default_factory=list)
    deleted_functions: list[str] = field(default_factory=list)
    referenced: set[str] = field(default_factory=set)
    truncated: int = 0

    @property
    def trace_files(self) -> list[str]:
        return sorted(set(self.head_required) | set(self.base_required))


@dataclass
class Run:
    calls: list[Call]
    indexes: tuple[int, int, int]
    ok: bool = True
    detail: str = ""
    base_res: dict[int, dict[str, Any]] = field(default_factory=dict)
    head_res: dict[int, dict[str, Any]] = field(default_factory=dict)
    again_res: dict[int, dict[str, Any]] = field(default_factory=dict)
    base_trace: dict[str, set[int]] | None = None
    head_trace: dict[str, set[int]] | None = None
    comparable: list[int] = field(default_factory=list)
    differing: list[int] = field(default_factory=list)
    new_api: list[int] = field(default_factory=list)


def module_name(path: str) -> str | None:
    pure = PurePosixPath(path)
    if pure.suffix != ".py":
        return None
    parts = pure.parent.parts if pure.name == "__init__.py" else pure.with_suffix("").parts
    if not parts or not all(part.isidentifier() for part in parts):
        return None
    return ".".join(parts)


def _read(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None


def _line_text(path: Path, line: int) -> str:
    text = _read(path)
    if text is None:
        return ""
    lines = text.splitlines()
    return lines[line - 1].strip() if 0 < line <= len(lines) else ""


def referenced_names(graph: CallGraph) -> set[str]:
    names: set[str] = set()
    for parsed in graph.files.values():
        for callees in parsed.calls.values():
            names.update(callees)
    return names


def analyze_changes(
    base_dir: Path,
    head_dir: Path,
    changes: dict[str, FileChange],
    limit: int = MAX_FUNCTIONS,
) -> Analysis:
    head_graph = build_callgraph(head_dir)
    base_graph = build_callgraph(base_dir)
    analysis = Analysis(referenced=referenced_names(head_graph))
    chosen: dict[str, Symbol] = {}
    module_files: set[str] = set()
    outside: dict[str, None] = {}
    new: dict[str, None] = {}
    deleted: dict[str, None] = {}

    sides = (
        ("head", head_graph, base_graph, head_dir, analysis.head_required),
        ("base", base_graph, head_graph, base_dir, analysis.base_required),
    )
    for file, change in sorted(changes.items()):
        if not file.endswith(".py") or is_test_file(file):
            continue
        for side, graph, other, root, required in sides:
            ranges = change.added if side == "head" else change.removed
            if not ranges:
                continue
            source = _read(root / file)
            parsed = graph.files.get(file)
            spans = statement_spans(source) if source is not None else None
            if source is None or parsed is None or spans is None:
                outside[f"{file} (could not be analyzed)"] = None
                continue
            classes = class_spans(source)
            for start, end in ranges:
                for line in range(start, min(end, start + MAX_LINES_PER_RANGE) + 1):
                    if line in parsed.blank_lines:
                        continue
                    symbol = graph.symbol_at_line(file, line)
                    statement = required_line(spans, line)
                    if symbol.is_module:
                        if any(first <= line <= last for first, last in classes):
                            outside[f"class body in {file}"] = None
                            continue
                        module_files.add(file)
                    else:
                        owner = symbol.qualname.split(".")[0]
                        key = f"{file}::{owner}"
                        if key not in graph.symbols:
                            outside[f"{symbol.qualname} ({file})"] = None
                            continue
                        if key not in other.symbols:
                            (new if side == "head" else deleted)[owner] = None
                            continue
                        chosen[key] = head_graph.symbols[key]
                    if statement is not None:
                        required.setdefault(file, set()).add(statement)

    for file in sorted(module_files):
        for symbol in head_graph.symbols.values():
            if symbol.file != file or symbol.is_module or "." in symbol.qualname:
                continue
            if symbol.key in base_graph.symbols:
                chosen.setdefault(symbol.key, symbol)
        if not any(symbol.file == file for symbol in chosen.values()):
            outside[f"module-level code in {file} (no function to call)"] = None

    for name in deleted:
        if name in analysis.referenced:
            outside[f"removed function {name} is still referenced"] = None

    ordered = sorted(chosen.values(), key=lambda symbol: (symbol.file, symbol.start))
    analysis.truncated = max(0, len(ordered) - limit)
    for symbol in ordered[:limit]:
        module = module_name(symbol.file)
        text = _read(head_dir / symbol.file)
        if module is None or text is None:
            outside[f"{symbol.qualname} ({symbol.file}, not importable)"] = None
            continue
        lines = text.splitlines()
        source = "\n".join(lines[symbol.start - 1 : symbol.end])[:MAX_SOURCE_CHARS]
        analysis.targets.append(Target(symbol.file, module, symbol.qualname, source))

    analysis.outside = list(outside)
    analysis.new_functions = list(new)
    analysis.deleted_functions = list(deleted)
    return analysis


def parse_calls(
    data: Any, targets: list[Target], claims: list[Claim], limit: int = MAX_CALLS
) -> list[Call]:
    items = data.get("calls") if isinstance(data, dict) else data
    if not isinstance(items, list):
        raise LLMError("calls must be a list")

    allowed = {(target.module, target.function) for target in targets}
    claim_ids = {claim.id for claim in claims}
    calls: list[Call] = []
    seen: set[str] = set()

    for item in items:
        if not isinstance(item, dict):
            continue
        module = item.get("module")
        function = item.get("function")
        if (module, function) not in allowed:
            continue
        args = item.get("args", [])
        kwargs = item.get("kwargs", {})
        if not isinstance(args, list) or not isinstance(kwargs, dict):
            continue
        if not all(isinstance(key, str) for key in kwargs):
            continue
        claim = item.get("claim")
        claim = claim if isinstance(claim, str) and claim in claim_ids else None
        try:
            key = json.dumps([module, function, args, kwargs], sort_keys=True)
        except (TypeError, ValueError):
            continue
        if len(key) > MAX_CALL_CHARS or key in seen:
            continue
        seen.add(key)
        calls.append(Call(module, function, args, kwargs, claim))
        if len(calls) >= limit:
            break
    return calls


def parse_results(stdout: str) -> dict[int, dict[str, Any]]:
    results: dict[int, dict[str, Any]] = {}
    for line in stdout.splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            record = json.loads(line)
        except ValueError:
            continue
        if isinstance(record, dict) and isinstance(record.get("i"), int):
            results[record["i"]] = record
    return results


def parse_trace(stdout: str) -> dict[str, set[int]] | None:
    found: dict[str, set[int]] | None = None
    for line in stdout.splitlines():
        line = line.strip()
        if not line.startswith('{"trace"'):
            continue
        try:
            record = json.loads(line)
        except ValueError:
            continue
        trace = record.get("trace") if isinstance(record, dict) else None
        if isinstance(trace, dict):
            found = {
                str(name): {number for number in numbers if isinstance(number, int)}
                for name, numbers in trace.items()
                if isinstance(numbers, list)
            }
    return found


def _outcome(record: dict[str, Any]) -> tuple[str, str]:
    if record.get("ok"):
        return ("ok", str(record.get("value", "")))
    return ("exc", str(record.get("exc", "?")))


def _signature(record: dict[str, Any]) -> tuple[str, str, str]:
    kind, detail = _outcome(record)
    return (kind, detail, str(record.get("state", "")))


def _label(record: dict[str, Any]) -> str:
    if record.get("ok"):
        return f"returned {record.get('value', '')}"
    return f"raised {record.get('exc', '?')}"


def _call_text(call: Call) -> str:
    parts = [repr(arg) for arg in call.args]
    parts += [f"{key}={value!r}" for key, value in call.kwargs.items()]
    text = f"{call.function}({', '.join(parts)})"
    return text if len(text) <= 120 else text[:117] + "..."


def _describe_difference(call: Call, base: dict[str, Any], head: dict[str, Any]) -> str:
    text = _call_text(call)
    if _outcome(base) == _outcome(head):
        return (
            f"{text} leaves its arguments as {base.get('state')} on base "
            f"but {head.get('state')} on head"
        )
    return f"{text} {_label(base)} on base but {_label(head)} on head"


def _is_new_signature(base: dict[str, Any], head: dict[str, Any]) -> bool:
    return bool(
        not base.get("ok")
        and base.get("exc") == "TypeError"
        and head.get("ok")
        and SIGNATURE_ERROR.search(str(base.get("msg", "")))
    )


def _call_key(call: Call) -> str:
    return json.dumps([call.module, call.function, call.args, call.kwargs], sort_keys=True)


def _prompt(ctx: AuditContext, claims: list[Claim], targets: list[Target]) -> str:
    functions = "\n\n".join(f"# {t.module}.{t.function}\n{t.source}" for t in targets)
    claim_lines = "\n".join(f"{c.id} ({c.kind.value}): {c.text}" for c in claims) or "(none)"
    return (
        f"PR title: {ctx.submission.title}\n\n"
        f"Claims:\n{claim_lines}\n\n"
        f"Functions to call (new version):\n{functions}\n\n"
        f"Diff (old to new):\n{ctx.diff[:MAX_DIFF_CHARS]}"
    )


class Characterizer:
    def __init__(
        self,
        llm: LLMClient,
        runner: CommandRunner,
        *,
        max_calls: int = MAX_CALLS,
        timeout_s: int = 60,
    ) -> None:
        self.llm = llm
        self.runner = runner
        self.max_calls = max_calls
        self.timeout_s = timeout_s

    def run(
        self,
        ctx: AuditContext,
        claims: list[Claim],
        changes: dict[str, FileChange],
        changed_files: list[str],
    ) -> AgentResult:
        result = AgentResult()
        no_change = [c for c in claims if c.kind is ClaimKind.NO_BEHAVIOR_CHANGE]
        fixes = [c for c in claims if c.kind is ClaimKind.FIXES]
        critical = [c for c in claims if c.kind in CRITICAL_KINDS]
        tests_changed = any(is_test_file(path) for path in changed_files)

        explanation = self._static(ctx, changed_files)
        if explanation is not None:
            return self._settled(result, no_change, "Static check: no runtime change", explanation)

        analysis = analyze_changes(ctx.base_dir, ctx.head_dir, changes)
        if not analysis.targets:
            return self._without_targets(result, no_change, analysis)

        try:
            calls = self._generate(ctx, critical, analysis.targets, self.max_calls)
        except LLMError as exc:
            result.findings.append(
                self._finding(
                    "Differential check skipped: input generation failed",
                    Severity.LOW,
                    str(exc)[:500],
                )
            )
            return result
        if not calls:
            result.findings.append(
                self._finding("Differential check skipped: no usable inputs", Severity.LOW)
            )
            return result

        run = self._execute(ctx, calls, analysis)
        if not run.ok:
            result.findings.append(
                Finding(
                    source="characterize",
                    title="Differential check could not run",
                    detail=run.detail,
                    severity=Severity.LOW,
                    command_indexes=list(run.indexes),
                )
            )
            return result

        missing = self._missing(analysis, run)
        if missing and len(calls) < MAX_TOTAL_CALLS:
            extra = self._more(ctx, critical, analysis, missing, calls)
            if extra:
                combined = calls + extra
                second = self._execute(ctx, combined, analysis)
                if second.ok:
                    run, missing = second, self._missing(analysis, second)

        self._conclude(result, no_change, fixes, analysis, run, missing, tests_changed)
        return result

    def _static(self, ctx: AuditContext, changed_files: list[str]) -> str | None:
        if not changed_files:
            return None
        for path in changed_files:
            if is_test_file(path) or path.endswith(DOC_SUFFIXES):
                continue
            if not path.endswith(".py"):
                return None
            base = _read(ctx.base_dir / path)
            head = _read(ctx.head_dir / path)
            if base is None or head is None or not same_syntax(base, head):
                return None
        return (
            "No non-test code changed apart from docstrings, comments and formatting, "
            "so the syntax trees are identical."
        )

    def _without_targets(
        self, result: AgentResult, no_change: list[Claim], analysis: Analysis
    ) -> AgentResult:
        if analysis.outside:
            result.findings.append(
                self._finding(
                    "Differential check skipped: changed code is outside its reach",
                    Severity.INFO,
                    "; ".join(analysis.outside[:6]),
                )
            )
            return result
        if analysis.new_functions or analysis.deleted_functions:
            names = ", ".join([*analysis.new_functions, *analysis.deleted_functions][:6])
            self._settled(
                result,
                no_change,
                "Structural check: no existing function changed",
                f"Only new or unreferenced removed functions changed ({names}).",
            )
            result.behavior_identical = not analysis.new_functions
            return result
        result.findings.append(
            self._finding(
                "Differential check skipped: no changed top-level Python function found",
                Severity.INFO,
            )
        )
        return result

    def _settled(
        self, result: AgentResult, no_change: list[Claim], title: str, explanation: str
    ) -> AgentResult:
        result.behavior_identical = True
        result.findings.append(self._finding(title, Severity.INFO, explanation))
        for claim in no_change:
            self._support(result, claim, explanation, [])
        return result

    def _generate(
        self, ctx: AuditContext, claims: list[Claim], targets: list[Target], limit: int
    ) -> list[Call]:
        system = SYSTEM.replace("{n}", str(limit))

        def parse(data: Any) -> list[Call]:
            calls = parse_calls(data, targets, claims, limit)
            if not calls:
                raise LLMError("none of the calls used the listed module and function names")
            return calls

        return complete_parsed(self.llm, system, _prompt(ctx, claims, targets), parse)

    def _more(
        self,
        ctx: AuditContext,
        claims: list[Claim],
        analysis: Analysis,
        missing: list[tuple[str, str, int]],
        existing: list[Call],
    ) -> list[Call]:
        room = MAX_TOTAL_CALLS - len(existing)
        if room <= 0:
            return []
        lines = []
        for side, file, line in missing[:MAX_UNCOVERED_SHOWN]:
            root = ctx.head_dir if side == "head" else ctx.base_dir
            label = "new" if side == "head" else "old"
            lines.append(f"{label} version {file}:{line}: {_line_text(root / file, line)}")
        used = json.dumps(
            [{"function": c.function, "args": c.args, "kwargs": c.kwargs} for c in existing]
        )[:3000]
        prompt = (
            _prompt(ctx, claims, analysis.targets)
            + "\n\nThese changed lines did not run under the inputs already used. "
            + "Add calls that execute them:\n"
            + "\n".join(lines)
            + f"\n\nInputs already used:\n{used}"
        )
        system = SYSTEM.replace("{n}", str(room))
        try:
            fresh = complete_parsed(
                self.llm,
                system,
                prompt,
                lambda data: parse_calls(data, analysis.targets, claims, room),
            )
        except LLMError:
            return []
        known = {_call_key(call) for call in existing}
        return [call for call in fresh if _call_key(call) not in known]

    def _files(self, calls: list[Call], trace_files: list[str]) -> dict[str, str]:
        payload = json.dumps(
            {
                "calls": [
                    {
                        "module": c.module,
                        "function": c.function,
                        "args": c.args,
                        "kwargs": c.kwargs,
                    }
                    for c in calls
                ],
                "trace": list(trace_files),
            }
        )
        return {
            f"{CHAR_DIR}/__init__.py": "",
            f"{CHAR_DIR}/driver.py": DRIVER,
            f"{CHAR_DIR}/calls.json": payload,
        }

    def _write(self, ctx: AuditContext, files: dict[str, str]) -> None:
        for root in (ctx.base_dir, ctx.head_dir):
            (root / CHAR_DIR).mkdir(exist_ok=True)
            for relative, content in files.items():
                (root / relative).write_text(content, encoding="utf-8")

    def _cleanup(self, ctx: AuditContext) -> None:
        for root in (ctx.base_dir, ctx.head_dir):
            shutil.rmtree(root / CHAR_DIR, ignore_errors=True)

    def _execute(self, ctx: AuditContext, calls: list[Call], analysis: Analysis) -> Run:
        files = self._files(calls, analysis.trace_files)
        self._write(ctx, files)
        try:
            base_idx, base_rec = ctx.evidence.run(
                self.runner, ctx.base_dir, ARGV, timeout_s=self.timeout_s, overlay=files
            )
            head_idx, head_rec = ctx.evidence.run(
                self.runner, ctx.head_dir, ARGV, timeout_s=self.timeout_s, overlay=files
            )
            again_idx, again_rec = ctx.evidence.run(
                self.runner, ctx.head_dir, ARGV, timeout_s=self.timeout_s, overlay=files
            )
        finally:
            self._cleanup(ctx)

        run = Run(calls=calls, indexes=(base_idx, head_idx, again_idx))
        run.base_res = parse_results(base_rec.stdout)
        run.head_res = parse_results(head_rec.stdout)
        run.again_res = parse_results(again_rec.stdout)
        records = (base_rec, head_rec, again_rec)
        if not (run.base_res and run.head_res and run.again_res) or any(
            is_infra_failure(record) for record in records
        ):
            run.ok = False
            run.detail = (head_rec.stderr or base_rec.stderr)[-500:]
            return run

        run.base_trace = parse_trace(base_rec.stdout)
        run.head_trace = parse_trace(head_rec.stdout)
        for i in range(len(calls)):
            if not (i in run.base_res and i in run.head_res and i in run.again_res):
                continue
            if _signature(run.head_res[i]) != _signature(run.again_res[i]):
                continue
            if _is_new_signature(run.base_res[i], run.head_res[i]):
                run.new_api.append(i)
                continue
            run.comparable.append(i)
            if _signature(run.base_res[i]) != _signature(run.head_res[i]):
                run.differing.append(i)
        return run

    def _missing(self, analysis: Analysis, run: Run) -> list[tuple[str, str, int]]:
        missing: list[tuple[str, str, int]] = []
        for side, required, trace in (
            ("head", analysis.head_required, run.head_trace),
            ("base", analysis.base_required, run.base_trace),
        ):
            for file in sorted(required):
                hit = (trace or {}).get(file, set())
                missing.extend((side, file, line) for line in sorted(required[file] - hit))
        return missing

    def _conclude(
        self,
        result: AgentResult,
        no_change: list[Claim],
        fixes: list[Claim],
        analysis: Analysis,
        run: Run,
        missing: list[tuple[str, str, int]],
        tests_changed: bool,
    ) -> None:
        calls = run.calls
        indexes = [run.indexes[0], run.indexes[1]]
        comparable, differing = run.comparable, run.differing

        if comparable and all(run.head_res[i].get("exc") in IMPORT_ERRORS for i in comparable):
            result.findings.append(
                Finding(
                    source="characterize",
                    title="Differential check could not import the changed modules",
                    severity=Severity.LOW,
                    command_indexes=indexes,
                )
            )
            return

        detail = ""
        if run.new_api:
            detail = (
                f"{len(run.new_api)} input(s) use a signature that exists only on the new "
                "version and were not compared."
            )
        result.findings.append(
            Finding(
                source="characterize",
                title=(
                    f"Differential check: {len(comparable)} input(s) compared, "
                    f"{len(differing)} differ"
                ),
                detail=detail,
                severity=Severity.INFO,
                command_indexes=indexes,
            )
        )

        if differing:
            examples = "; ".join(
                _describe_difference(calls[i], run.base_res[i], run.head_res[i])
                for i in differing[:3]
            )
            for claim in no_change:
                self._refute(result, claim, f"Behavior differs: {examples}", indexes)
            if not no_change and (fixes or tests_changed):
                result.findings.append(
                    Finding(
                        source="characterize",
                        title=f"Behavior differs on {len(differing)} input(s)",
                        detail=examples,
                        severity=Severity.INFO,
                        command_indexes=indexes,
                    )
                )
            elif not no_change:
                result.findings.append(
                    Finding(
                        source="characterize",
                        title=f"Behavior change not declared: {len(differing)} input(s) differ",
                        detail=examples,
                        severity=Severity.MEDIUM,
                        command_indexes=indexes,
                    )
                )

        if missing:
            shown = ", ".join(f"{file}:{line}" for _, file, line in missing[:8])
            result.findings.append(
                Finding(
                    source="characterize",
                    title="Changed code never exercised by the differential inputs",
                    detail=f"{len(missing)} changed line(s) did not run, for example {shown}.",
                    severity=Severity.MEDIUM,
                    command_indexes=indexes,
                )
            )
        if analysis.outside:
            result.findings.append(
                self._finding(
                    "Not differentially checked: " + "; ".join(analysis.outside[:4]),
                    Severity.INFO,
                )
            )
        if analysis.truncated:
            result.findings.append(
                self._finding(
                    f"Differential check limited to {MAX_FUNCTIONS} functions",
                    Severity.INFO,
                    f"{analysis.truncated} more changed function(s) were not compared.",
                )
            )

        identical = (
            not differing
            and bool(comparable)
            and not missing
            and not analysis.outside
            and not analysis.truncated
        )
        if identical:
            result.behavior_identical = not analysis.new_functions
            for claim in no_change:
                self._support(
                    result,
                    claim,
                    f"{len(comparable)} input(s) gave the same results and argument state on "
                    "both commits, and every changed line ran.",
                    indexes,
                )

        differing_set = set(differing)
        for claim in fixes:
            targeted = [i for i in comparable if calls[i].claim == claim.id]
            if not targeted:
                continue
            recovered = [
                i for i in targeted if not run.base_res[i].get("ok") and run.head_res[i].get("ok")
            ]
            if recovered:
                examples = "; ".join(
                    f"{_call_text(calls[i])} {_label(run.base_res[i])} on base and "
                    f"{_label(run.head_res[i])} on head"
                    for i in recovered[:3]
                )
                self._support(
                    result,
                    claim,
                    f"The input described by the claim now succeeds: {examples}",
                    indexes,
                )
            elif not differing_set.intersection(targeted):
                failing = [i for i in targeted if not run.head_res[i].get("ok")]
                if failing:
                    examples = "; ".join(
                        f"{_call_text(calls[i])} {_label(run.head_res[i])} on both versions"
                        for i in failing[:3]
                    )
                    self._refute(
                        result,
                        claim,
                        f"The input described by the claim still fails: {examples}",
                        indexes,
                    )

    @staticmethod
    def _finding(title: str, severity: Severity, detail: str = "") -> Finding:
        return Finding(source="characterize", title=title, detail=detail, severity=severity)

    @staticmethod
    def _support(result: AgentResult, claim: Claim, explanation: str, indexes: list[int]) -> None:
        result.claim_results.append(
            ClaimResult(
                claim_id=claim.id,
                status=ClaimStatus.SUPPORTED,
                explanation=explanation[:1000],
                command_indexes=indexes,
            )
        )

    @staticmethod
    def _refute(result: AgentResult, claim: Claim, explanation: str, indexes: list[int]) -> None:
        result.claim_results.append(
            ClaimResult(
                claim_id=claim.id,
                status=ClaimStatus.REFUTED,
                explanation=explanation[:1000],
                command_indexes=indexes,
            )
        )
        result.findings.append(
            Finding(
                source="characterize",
                title=f"Claim refuted: {claim.text}",
                detail=explanation[:1000],
                severity=Severity.HIGH,
                command_indexes=indexes,
            )
        )


def merge_characterization(audit: AgentResult, extra: AgentResult, claims: list[Claim]) -> None:
    by_id = {claim.id: claim for claim in claims}
    for new in extra.claim_results:
        claim = by_id.get(new.claim_id)
        if claim is None:
            continue
        prior = [r for r in audit.claim_results if r.claim_id == new.claim_id]
        if any(r.status is ClaimStatus.REFUTED for r in prior):
            continue
        indexes = sorted({*new.command_indexes, *(i for r in prior for i in r.command_indexes)})
        audit.claim_results = [r for r in audit.claim_results if r.claim_id != new.claim_id]
        audit.claim_results.append(new.model_copy(update={"command_indexes": indexes}))
        stale = f"Claim not verified: {claim.text}"
        audit.findings = [f for f in audit.findings if f.title != stale]

    titles = {finding.title for finding in audit.findings}
    for finding in extra.findings:
        if finding.title not in titles:
            audit.findings.append(finding)
            titles.add(finding.title)
