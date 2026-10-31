"""Verify optional integrations stay authenticated and disabled without policy."""

from fastapi import FastAPI
from fastapi.testclient import TestClient

from orchestrator.config import Settings
from orchestrator.events import EventCollector
from orchestrator.integration_routes import router
from orchestrator.integrations import IntegrationServices
from orchestrator.storage import Store


def test_publication_requires_auth_and_explicit_permission(tmp_path):
    """A configured route never makes an external call under default permissions."""
    store = Store(tmp_path / "records.sqlite")
    store.put("runs", "lab", "run", {"run_id": "run", "project_id": "lab"})
    app = FastAPI()
    app.state.settings = Settings(token="test-internal-only", data_dir=tmp_path)
    app.state.integrations = IntegrationServices.from_env(
        store, EventCollector(store, tmp_path / "events"), {})
    app.include_router(router)
    payload = {"path": "out.md", "content": "# Local only", "idempotency_key": "once"}
    try:
        with TestClient(app) as client:
            path = "/v1/runs/run/integrations/documents?project_id=lab"
            assert client.post(path, json=payload).status_code == 401
            response = client.post(path, json=payload,
                                   headers={"Authorization": "Bearer test-internal-only"})
            assert response.status_code == 403
            assert store.list("document_admissions", "lab") == []
    finally:
        app.state.integrations.close()
        store.close()
