import json
from pathlib import Path

from tribunal.agents.characterize import DRIVER
from tribunal.llm import ScriptedLLM
from tribunal.replay import replay_receipt


def test_probe_commands_carry_their_files(
    scenario, make_runner, make_pipeline, probes_json
) -> None:
    repo, shas = scenario
    probe_code = json.loads(probes_json)["probes"][0]["code"]

    def handler(workdir: Path, argv: list[str]) -> tuple[int, str, str]:
        return 0, "ok", ""

    fake = make_runner(handler)
    pipe = make_pipeline(fake, ScriptedLLM([probes_json]))
    submission = pipe.submit(repo_path=str(repo), base=shas[0], head=shas[1])
    receipt = pipe.run(submission.id)

    body = receipt.body
    assert body.version == 2
    assert len(body.commands) == 1
    command = body.commands[0]
    assert command.side == "head"
    assert command.timeout_s == 30
    assert set(command.overlay) == {"tribunal_probes/__init__.py", "tribunal_probes/probe_1.py"}
    assert body.blobs[command.overlay["tribunal_probes/probe_1.py"]] == probe_code

    checked = []

    def replay_handler(workdir: Path, argv: list[str]) -> tuple[int, str, str]:
        probe_file = workdir / "tribunal_probes" / "probe_1.py"
        checked.append(probe_file.exists() and probe_file.read_text() == probe_code)
        return 0, "ok", ""

    report = replay_receipt(receipt, repo, lambda image: make_runner(replay_handler))
    assert report.overall == "reproduced"
    assert checked == [True]


def test_differential_commands_carry_driver_inputs_and_trace_files(
    scenario, make_runner, make_pipeline, probes_json, is_head
) -> None:
    repo, shas = scenario

    def handler(workdir: Path, argv: list[str]) -> tuple[int, str, str]:
        if argv[-1].endswith("driver"):
            value = "3" if is_head(workdir) else "2"
            lines = [
                json.dumps({"i": 0, "ok": True, "value": value, "state": "[[1], {}]"}),
                json.dumps({"trace": {"lib.py": [1, 2]}}),
            ]
            return 0, "\n".join(lines), ""
        return 0, "ok", ""

    llm = ScriptedLLM(
        [
            json.dumps({"claims": [{"text": "no behavior change", "kind": "no_behavior_change"}]}),
            json.dumps({"checks": []}),
            probes_json,
            json.dumps(
                {
                    "calls": [
                        {"module": "lib", "function": "f", "args": [1], "kwargs": {}, "claim": None}
                    ]
                }
            ),
        ]
    )
    fake = make_runner(handler)
    pipe = make_pipeline(fake, llm)
    submission = pipe.submit(
        repo_path=str(repo),
        base=shas[0],
        head=shas[1],
        title="Refactor f",
        description="No behavior change.",
    )
    receipt = pipe.run(submission.id)

    body = receipt.body
    assert len(body.commands) == 4
    drivers = [c for c in body.commands if c.argv[-1].endswith("driver")]
    assert [c.side for c in drivers] == ["base", "head", "head"]
    for command in drivers:
        assert set(command.overlay) == {
            "tribunal_chars/__init__.py",
            "tribunal_chars/driver.py",
            "tribunal_chars/calls.json",
        }
        assert body.blobs[command.overlay["tribunal_chars/driver.py"]] == DRIVER
    spec = json.loads(body.blobs[drivers[0].overlay["tribunal_chars/calls.json"]])
    assert spec["calls"] == [{"module": "lib", "function": "f", "args": [1], "kwargs": {}}]
    assert spec["trace"] == ["lib.py"]

    report = replay_receipt(receipt, repo, lambda image: fake)
    assert report.overall == "reproduced"
    assert report.as_dict()["commands"] == 4
