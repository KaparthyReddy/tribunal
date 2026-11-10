import pytest
from fastapi.testclient import TestClient

from tribunal.api import create_app
from tribunal.config import Settings
from tribunal.llm import ScriptedLLM


@pytest.fixture
def pipe(scenario, make_runner, make_pipeline, probes_json):
    runner = make_runner(lambda workdir, argv: (0, "ok", ""))
    return make_pipeline(runner, ScriptedLLM([probes_json] * 4))


@pytest.fixture
def client(pipe) -> TestClient:
    return TestClient(create_app(pipeline=pipe, settings=Settings(_env_file=None)))


def _payload(scenario, **extra) -> dict:
    repo, shas = scenario
    return {"repo_path": str(repo), "base": shas[0], "head": shas[1], **extra}


def test_health(client: TestClient) -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_submit_wait_returns_receipt(client: TestClient, scenario) -> None:
    response = client.post("/submissions", json=_payload(scenario, wait=True, agent="codex"))
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "complete"
    assert body["receipt"]["body"]["verdict"] == "pass"

    receipt_id = body["receipt"]["body"]["receipt_id"]
    assert client.get(f"/receipts/{receipt_id}").json() == body["receipt"]
    by_submission = client.get(f"/submissions/{body['submission_id']}/receipt")
    assert by_submission.json() == body["receipt"]


def test_submit_background(client: TestClient, scenario) -> None:
    response = client.post("/submissions", json=_payload(scenario))
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "queued"
    assert body["receipt"] is None

    fetched = client.get(f"/submissions/{body['submission_id']}")
    assert fetched.json()["status"] == "complete"
    assert client.get(f"/submissions/{body['submission_id']}/receipt").status_code == 200
    assert len(client.get("/submissions").json()) == 1


def test_bad_submission_is_rejected(client: TestClient, scenario, tmp_path) -> None:
    response = client.post("/submissions", json=_payload(scenario, base="nope"))
    assert response.status_code == 400
    response = client.post(
        "/submissions",
        json={"repo_path": str(tmp_path / "missing"), "base": "a", "head": "b"},
    )
    assert response.status_code == 400


def test_unknown_resources_404(client: TestClient) -> None:
    assert client.get("/submissions/sub_nope").status_code == 404
    assert client.get("/submissions/sub_nope/receipt").status_code == 404
    assert client.get("/receipts/rcp_nope").status_code == 404


def test_verify_endpoint(client: TestClient, scenario) -> None:
    receipt = client.post("/submissions", json=_payload(scenario, wait=True)).json()["receipt"]

    ok = client.post("/receipts/verify", json=receipt)
    assert ok.json() == {"intact": True, "trusted": True}

    receipt["body"]["verdict"] = "fail"
    tampered = client.post("/receipts/verify", json=receipt)
    assert tampered.json()["intact"] is False


def test_trust_and_public_key(client: TestClient, scenario, pipe) -> None:
    client.post("/submissions", json=_payload(scenario, wait=True, agent="codex"))
    trust = client.get("/agents/codex/trust").json()
    assert trust["total"] == 1
    assert trust["passes"] == 1
    assert trust["scrutiny"] == "standard"
    assert client.get("/public-key").json() == {"public_key": pipe.signer.public_key_b64}


def test_token_auth(pipe, scenario) -> None:
    app = create_app(pipeline=pipe, settings=Settings(_env_file=None, api_token="s3cret"))
    secured = TestClient(app)

    assert secured.get("/health").status_code == 200
    assert secured.get("/submissions").status_code == 401
    wrong = secured.get("/submissions", headers={"Authorization": "Bearer nope"})
    assert wrong.status_code == 401
    right = secured.get("/submissions", headers={"Authorization": "Bearer s3cret"})
    assert right.status_code == 200
