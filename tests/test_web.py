import pytest
from fastapi.testclient import TestClient

from replaylab.demo import FIXED_PROMPT, research_workflow
from replaylab.providers import MockProvider
from replaylab.store import Store
from replaylab.web import create_app


@pytest.fixture
def client(tmp_path):
    store = Store(tmp_path / "trace.sqlite")
    return TestClient(
        create_app(store, {"research": research_workflow(MockProvider())}),
        base_url="http://127.0.0.1",
    )


def test_api_records_demo_inspects_forks_replays_and_compares(client):
    assert client.get("/api/runs").json() == []
    demo = client.post("/api/demo").json()
    original = demo["original"]
    detail = client.get(f"/api/runs/{original}")
    assert detail.status_code == 200
    assert detail.json()["steps"][3]["error"] is not None
    fork = client.post(
        f"/api/runs/{original}/fork", json={"position": 4, "changes": {"prompt": FIXED_PROMPT}}
    )
    assert fork.status_code == 201
    fork_id = fork.json()["id"]
    assert fork.json()["status"] == "completed"
    comparison = client.get("/api/diff", params={"left": original, "right": fork_id}).json()
    assert comparison["changed"] == 2
    assert len(client.get("/api/runs").json()) == 3
    replay = client.post(f"/api/runs/{fork_id}/replay")
    assert replay.status_code == 201
    assert replay.json()["status"] == "completed"


def test_api_rejects_invalid_run_and_fork(client):
    assert client.get("/api/runs/missing").status_code == 404
    demo = client.post("/api/demo").json()
    url = f"/api/runs/{demo['original']}/fork"
    assert (
        client.post(url, json={"position": 999, "changes": {"prompt": "fixed"}}).status_code == 422
    )
    assert client.post(url, json={"position": 2, "changes": {"prompt": "fixed"}}).status_code == 422
    assert (
        client.post(url, json={"position": True, "changes": {"tool_result": 1}}).status_code == 422
    )
    assert client.post(url, json={"position": 2, "changes": {}, "extra": 1}).status_code == 422


def test_local_security_rejects_foreign_origin_and_dns_rebinding(client):
    assert client.post("/api/demo", headers={"origin": "https://evil.test"}).status_code == 403
    assert client.get("/api/runs", headers={"host": "evil.test"}).status_code == 400
    response = client.post("/api/demo", headers={"origin": "http://127.0.0.1"})
    assert response.status_code == 201
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["cache-control"] == "no-store"


def test_ui_static_assets_and_csp(client):
    response = client.get("/")
    assert response.status_code == 200
    assert "Replaylab" in response.text
    assert "default-src 'self'" in response.headers["content-security-policy"]
    assert client.get("/static/app.js").status_code == 200
    assert client.get("/static/style.css").status_code == 200


def test_database_workflow_name_cannot_trigger_code_import(tmp_path):
    store = Store(tmp_path / "trace.sqlite")
    run_id = store.create_run("os:system", {}, "record", None, None)
    store.finish_run(run_id, "completed", None, None)
    client = TestClient(create_app(store, {}), base_url="http://127.0.0.1")
    assert client.post(f"/api/runs/{run_id}/replay").status_code == 409
