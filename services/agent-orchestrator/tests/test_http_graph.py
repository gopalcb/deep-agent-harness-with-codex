"""Check authenticated route wiring and exact NestJS transport contracts offline."""

import httpx
from fastapi.testclient import TestClient

from orchestrator.api import create_app
from orchestrator.codex_client import CodexClient
from orchestrator.config import Settings
from orchestrator.contracts import TaskAssignment, TaskResult
from orchestrator.events import EventCollector
from orchestrator.planning import DemoPlanner
from orchestrator.storage import Store
from orchestrator.workflow import WorkflowService


def test_codex_client_frozen_endpoints():
    """All client operations preserve trusted scope, bearer auth and repair keys."""
    seen = []
    task = TaskAssignment(
        project_id="lab", run_id="run", task_id="api", instruction="do", idempotency_key="start-1"
    )

    def handle(request: httpx.Request) -> httpx.Response:
        """Return boundary fixtures while capturing the actual wire requests."""
        seen.append(request)
        assert request.headers["Authorization"] == "Bearer internal-test"
        if request.url.path.endswith("events"):
            return httpx.Response(200, json=[])
        return httpx.Response(
            200,
            json=TaskResult(
                project_id="lab", run_id="run", task_id="api", status="running"
            ).model_dump(),
        )

    client = CodexClient("http://codex.invalid", "internal-test", httpx.MockTransport(handle))
    try:
        assert client.start(task).status == "running"
        client.status("lab", "run", "api")
        client.resume("lab", "run", "api", "repair", "repair-1")
        client.cancel("lab", "run", "api")
        assert client.events("lab", "run", "api", 42) == []
    finally:
        client.close()
    assert [request.method for request in seen] == ["POST", "GET", "POST", "POST", "GET"]
    assert seen[1].url.params["project_id"] == "lab"
    assert seen[-1].url.params["after"] == "42"
    assert seen[2].url.path == "/internal/v1/tasks/api/resume"


def test_api_auth_scope_and_advancement(tmp_path):
    """The public contract admits, schedules, advances and replays a disposable run."""

    def handle(request: httpx.Request) -> httpx.Response:
        """Keep all transport activity in-process and credential-free."""
        if request.url.path.endswith("events"):
            return httpx.Response(200, json=[])
        if request.method == "POST" and request.url.path.endswith("tasks"):
            import json

            task = json.loads(request.content)
            return httpx.Response(
                200,
                json={
                    "project_id": task["project_id"],
                    "run_id": task["run_id"],
                    "task_id": task["task_id"],
                    "status": "succeeded",
                    "checks": [{"id": "fixture", "status": "passed", "exit_code": 0}],
                },
            )
        raise AssertionError(f"unexpected {request.method} {request.url}")

    store = Store(tmp_path / "records.sqlite")
    codex = CodexClient("http://codex.invalid", "test", httpx.MockTransport(handle))
    service = WorkflowService(
        store,
        EventCollector(store, tmp_path / "events"),
        codex,
        str(tmp_path / "graph.sqlite"),
        DemoPlanner(),
    )
    app = create_app(service, Settings(token="test", data_dir=tmp_path))
    headers = {"Authorization": "Bearer test"}
    try:
        with TestClient(app) as client:
            assert client.get("/health").status_code == 200
            assert client.post("/v1/runs", json={}).status_code == 401
            response = client.post(
                "/v1/runs",
                headers=headers,
                json={
                    "project_id": "lab",
                    "instruction": "change fixture",
                    "idempotency_key": "one",
                },
            )
            assert response.status_code == 200
            run_id = response.json()["run_id"]
            for unused in range(4):
                result = client.post(f"/v1/runs/{run_id}/advance", headers=headers)
            assert result.json()["status"] == "succeeded"
            assert (
                client.get(f"/v1/runs/{run_id}?project_id=foreign", headers=headers).status_code
                == 404
            )
            assert client.get(f"/v1/runs/{run_id}/events", headers=headers).json()
    finally:
        service.close()
        store.close()
        codex.close()


async def test_scheduler_filters_terminal_history_and_rotates_active_runs():
    """Historical completions and a full active page cannot starve later runs."""
    from types import SimpleNamespace

    from orchestrator.api import advance_active_round

    runs = [
        {"run_id": f"history-{index:03}", "status": "succeeded", "tasks": []}
        for index in range(150)
    ]
    runs += [
        {"run_id": f"active-{index:03}", "status": "running", "tasks": []} for index in range(205)
    ]
    runs.append(
        {"run_id": "terminal-replay", "status": "failed", "tasks": [{"event_replay_pending": True}]}
    )
    seen = []

    def list_runs(namespace: str, project_id: str) -> list:
        """Return the unfiltered persistent history before active work."""
        return runs

    def advance(project_id: str, run_id: str) -> None:
        """Record scheduling without making each active invocation terminal."""
        seen.append(run_id)

    app = SimpleNamespace(
        state=SimpleNamespace(
            projects={"lab"},
            workflow=SimpleNamespace(store=SimpleNamespace(list=list_runs), advance=advance),
        )
    )
    cursors = {}
    for unused in range(3):
        before = len(seen)
        await advance_active_round(app, cursors)
        assert len(seen) - before == 100
    assert len(set(seen)) == 206
    assert "terminal-replay" in seen
    assert not any(run_id.startswith("history-") for run_id in seen)
