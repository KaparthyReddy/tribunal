from dataclasses import dataclass
from pathlib import Path

from tribunal.agents.base import AgentResult
from tribunal.graph import Symbol, build_callgraph, is_test_file
from tribunal.models import Finding, Severity


def _is_test_symbol(symbol: Symbol) -> bool:
    return is_test_file(symbol.file) and not symbol.is_module and symbol.name.startswith("test")


@dataclass
class BlastRadius:
    depth: int = 4
    wide_threshold: int = 25
    high_dependents: int = 5
    max_findings: int = 8

    def analyze(self, head_dir: Path, ranges: dict[str, list[tuple[int, int]]]) -> AgentResult:
        result = AgentResult()
        graph = build_callgraph(head_dir)

        skipped = sorted(f for f in ranges if not f.endswith(".py"))
        if skipped:
            result.findings.append(
                Finding(
                    source="blast_radius",
                    title=f"{len(skipped)} non-Python file(s) changed and not analyzed",
                    detail=", ".join(skipped[:10]),
                    severity=Severity.INFO,
                )
            )

        changed: dict[str, Symbol] = {}
        for file, spans in sorted(ranges.items()):
            if not file.endswith(".py") or is_test_file(file):
                continue
            for start, end in spans:
                for symbol in graph.symbols_in(file, start, end):
                    changed[symbol.key] = symbol

        module_files = sorted({s.file for s in changed.values() if s.is_module})
        if module_files:
            result.findings.append(
                Finding(
                    source="blast_radius",
                    title="Module-level changes are not coverage-checked",
                    detail=", ".join(module_files[:10]),
                    severity=Severity.INFO,
                )
            )

        functions = [s for s in changed.values() if not s.is_module]
        dependents_all: set[str] = set()
        uncovered: list[tuple[Symbol, list[str]]] = []

        for symbol in functions:
            reach = graph.callers_closure(symbol.key, self.depth)
            tests = [k for k in reach if _is_test_symbol(graph.symbols[k])]
            dependents = [
                k
                for k in reach
                if not is_test_file(graph.symbols[k].file) and not graph.symbols[k].is_module
            ]
            dependents_all.update(dependents)
            if not tests:
                uncovered.append((symbol, dependents))

        uncovered.sort(key=lambda item: len(item[1]), reverse=True)
        for symbol, dependents in uncovered[: self.max_findings]:
            names = ", ".join(sorted(graph.symbols[k].qualname for k in dependents)[:5])
            severity = Severity.HIGH if len(dependents) >= self.high_dependents else Severity.MEDIUM
            detail = f"{len(dependents)} dependent function(s) within depth {self.depth}."
            if names:
                detail += f" Callers include: {names}."
            result.findings.append(
                Finding(
                    source="blast_radius",
                    title=f"No test reaches changed code: {symbol.qualname} ({symbol.file})",
                    detail=detail,
                    severity=severity,
                )
            )
        remaining = len(uncovered) - self.max_findings
        if remaining > 0:
            result.findings.append(
                Finding(
                    source="blast_radius",
                    title=f"{remaining} more changed function(s) have no test coverage",
                    severity=Severity.MEDIUM,
                )
            )

        if len(dependents_all) > self.wide_threshold:
            result.findings.append(
                Finding(
                    source="blast_radius",
                    title=f"Wide blast radius: {len(dependents_all)} dependent function(s)",
                    detail=f"Within call depth {self.depth} of the changed code.",
                    severity=Severity.LOW,
                )
            )
        return result
