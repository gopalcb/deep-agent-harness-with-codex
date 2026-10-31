"""Verify optional runtime integrations fail closed using credential-free boundaries."""

import httpx
import pytest

from orchestrator.events import EventCollector
from orchestrator.integrations import IntegrationServices
from orchestrator.memory import MemoryStore
from orchestrator.storage import Store
from orchestrator.tools import ScopedTools


def test_configured_construction_no_network_no_secret_storage(tmp_path, monkeypatch):
    """Construct real supported adapters without connecting or persisting credentials."""

    def forbid_send(*args, **kwargs):
        """Make any accidental startup request fail immediately."""
        raise AssertionError("startup contacted network")

    monkeypatch.setattr(httpx.Client, "send", forbid_send)
    store = Store(tmp_path / "state.db")
    events = EventCollector(store, tmp_path / "logs")
    integrations = IntegrationServices.from_env(
        store,
        events,
        {
            "LAB_DOCUMENT_URL": "https://documents.test",
            "LAB_DOCUMENT_TOKEN": "fake-document-secret",
            "LAB_MCP_URL": "https://mcp.test/mcp",
            "LAB_MCP_TOKEN": "fake-mcp-secret",
            "LAB_MCP_TOOLS": '{"research":["search"]}',
            "LAB_INTEGRATION_PERMISSIONS": "search_documents,mcp_call",
        },
    )
    assert integrations.publisher is not None
    assert integrations.mcp_config["agent_tools"] == {"research": {"search"}}
    assert "fake-document-secret" not in repr(integrations)
    assert b"fake-document-secret" not in store.path.read_bytes()
    assert b"fake-mcp-secret" not in store.path.read_bytes()
    integrations.close()


@pytest.mark.parametrize(
    "config",
    [
        {"LAB_DOCUMENT_URL": "https://documents.test"},
        {"LAB_MCP_TOKEN": "fake"},
        {"LAB_INTEGRATION_PERMISSIONS": "shell"},
        {
            "LAB_MCP_URL": "https://mcp.test",
            "LAB_MCP_TOKEN": "fake",
            "LAB_MCP_TOOLS": '{"research":"shell"}',
        },
        {"LAB_MCP_URL": "http://mcp.test", "LAB_MCP_TOKEN": "fake"},
    ],
)
def test_invalid_configuration_fails_closed(tmp_path, config):
    """Missing auth and invalid scopes cannot create usable adapters."""
    store = Store(tmp_path / "state.db")
    with pytest.raises(ValueError):
        IntegrationServices.from_env(store, EventCollector(store, tmp_path / "logs"), config)


@pytest.mark.asyncio
async def test_disabled_and_scope_denied(tmp_path):
    """Missing permission and unknown run scope reject before any transport call."""
    store = Store(tmp_path / "state.db")
    events = EventCollector(store, tmp_path / "logs")
    integrations = IntegrationServices.from_env(store, events, {})
    with pytest.raises(PermissionError):
        integrations.publish("a", "r", "a.md", "# A", "key")
    integrations.permissions = {"publish_markdown", "mcp_call"}
    with pytest.raises(KeyError):
        integrations.publish("a", "r", "a.md", "# A", "key")
    store.put("runs", "a", "r", {"run_id": "r"})
    with pytest.raises(ValueError):
        await integrations.mcp_call("a", "r", "research", "search", {})


def test_scoped_document_methods_and_wrappers(tmp_path):
    """Explicit permissions expose only configured wrappers and bind runtime identity."""
    store = Store(tmp_path / "state.db")
    events = EventCollector(store, tmp_path / "logs")
    store.put("runs", "a", "r", {"run_id": "r"})
    calls = []

    class FakePublisher:
        """Record transport-bound scope without a network connection."""

        def publish(self, *args, **kwargs):
            """Return a deterministic fake receipt."""
            calls.append(args)
            return {"status": "READY"}

        def search(self, project_id, query):
            """Return fake scoped search results."""
            return [{"project_id": project_id, "query": query}]

        def reconcile(self, project_id, key):
            """Return a fake reconciliation receipt."""
            return {"project_id": project_id, "key": key}

    publisher = FakePublisher()
    integrations = IntegrationServices(
        store, events, {"publish_markdown", "search_documents", "reconcile_markdown"}, publisher
    )
    assert integrations.publish("a", "r", "a.md", "# A", "k")["status"] == "READY"
    assert calls[0][:2] == ("a", "r")
    assert integrations.search("a", "r", "fact")[0]["project_id"] == "a"
    with pytest.raises(KeyError):
        integrations.reconcile("a", "r", "other-run")
    store.put("document_admissions", "a", "k", {"run_id": "r"})
    assert integrations.reconcile("a", "r", "k")["key"] == "k"
    permissions = {"publish_markdown", "search_documents", "get_codex_status"}
    tools = ScopedTools(
        "a", "r", store, events, MemoryStore(store), publisher=publisher, permissions=permissions
    )
    wrappers = {tool.name: tool for tool in tools.langchain_tools()}
    assert set(wrappers) == {"publish_markdown", "search_documents"}
    wrappers["publish_markdown"].invoke({"path": "a.md", "content": "# A", "idempotency_key": "k"})
    assert calls[-1][:2] == ("a", "r")
    assert not ScopedTools(
        "a", "r", store, events, MemoryStore(store), publisher=publisher, permissions=set()
    ).langchain_tools()
