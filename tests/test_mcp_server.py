import asyncio

import pytest

from tribunal.llm import ScriptedLLM
from tribunal.mcp_server import TribunalTools, create_server


@pytest.fixture
def pipe(make_runner, make_pipeline, probes_json):
    runner = make_runner(lambda workdir, argv: (0, "ok", ""))
    return make_pipeline(runner, ScriptedLLM([probes_json] * 3))


def test_submit_verdict_verify(scenario, pipe) -> None:
    repo, shas = scenario
    tools = TribunalTools(lambda: pipe)

    result = tools.submit(repo_path=str(repo), base=shas[0], head=shas[1], agent="codex")
    assert result["verdict"] == "pass"
    assert result["head_sha"] == shas[1]

    status = tools.verdict(result["submission_id"])
    assert status["status"] == "complete"
    assert status["receipt_id"] == result["receipt_id"]

    checked = tools.verify(result["receipt_id"])
    assert checked == {"receipt_id": result["receipt_id"], "intact": True, "trusted": True}


def test_errors_are_returned_not_raised(scenario, pipe) -> None:
    repo, shas = scenario
    tools = TribunalTools(lambda: pipe)

    assert "error" in tools.submit(repo_path=str(repo), base="nope", head=shas[1])
    assert "error" in tools.verdict("sub_missing")
    assert "error" in tools.verify("rcp_missing")


def test_server_registers_tools(pipe) -> None:
    server = create_server(pipeline=pipe)
    listed = asyncio.run(server.list_tools())
    assert {tool.name for tool in listed} == {"submit", "verdict", "verify"}
