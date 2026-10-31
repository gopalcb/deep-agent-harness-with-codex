"""Exercise durable admissions, event recovery, scoped memory and external write safety."""

import json
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta

import httpx
import pytest

from orchestrator.documents import MarkdownPublisher, validate_document_path
from orchestrator.events import EventCollector
from orchestrator.memory import MemoryStore
from orchestrator.storage import Store
from orchestrator.tools import MCPTools, ScopedTools


def test_atomic_claim_and_scope(tmp_path):
    """Only one concurrent caller wins and changes never reuse an admission."""
    store = Store(tmp_path / "state.db")
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(
            pool.map(lambda _: store.claim("tasks", "a", "one", {"input": 1}), range(30))
        )
    assert sum(created for _, created in results) == 1
    with pytest.raises(ValueError):
        store.claim("tasks", "a", "one", {"input": 2})
    assert Store(store.path).get("tasks", "a", "one") == {"input": 1}
    assert store.get("tasks", "b", "one") is None


def test_replay_rotation_redaction_restart(tmp_path):
    """Replay is scoped, deduplicated, redacted and reconstructible after export loss."""
    store = Store(tmp_path / "state.db")
    events = EventCollector(store, tmp_path / "logs", max_bytes=512)
    first = events.emit(
        "a",
        "r",
        "tool.called",
        {"access_token": "PRIVATE", "text": "Bearer PRIVATE2", "usage": {"input_tokens": 42}},
    )
    # Telemetry counts are useful and should survive redaction.
    assert first["metadata"]["usage"]["input_tokens"] == 42
    original = {key: value for key, value in first.items() if key != "sequence"}
    original["metadata"] = {
        "access_token": "PRIVATE",
        "text": "Bearer PRIVATE2",
        "usage": {"input_tokens": 42},
    }
    assert events.append(original) == first
    with pytest.raises(ValueError):
        events.append({**original, "event_type": "different"})
    events.emit("b", "r", "other")
    events.emit("a", "r", "done")
    assert len(events.replay("a", "r")) == 2
    assert len(events.replay("a", "r", first["sequence"])) == 1
    for path in (tmp_path / "logs").glob("*.jsonl"):
        assert "PRIVATE" not in path.read_text()
        path.unlink()
    recovered = EventCollector(Store(store.path), tmp_path / "logs", max_bytes=512)
    exported = [
        json.loads(line)
        for path in sorted((tmp_path / "logs").glob("*.jsonl"))
        for line in path.read_text().splitlines()
    ]
    assert len(exported) == 3
    assert recovered.replay("a", "r") == events.replay("a", "r")
    assert b"PRIVATE" not in store.path.read_bytes()


def test_memory_review_expiry_scope(tmp_path):
    """Candidates require real check provenance, review and unexpired scope."""
    memory = MemoryStore(Store(tmp_path / "state.db"))
    expiry = (datetime.now(UTC) + timedelta(days=1)).isoformat()
    item = memory.save_candidate(
        "a", "Fact", "diff:1", [{"passed": True, "source": "test:1"}], expiry
    )
    assert not memory.retrieve("a")
    with pytest.raises(KeyError):
        memory.promote("b", item["id"], "human")
    memory.promote("a", item["id"], "human")
    assert memory.retrieve("a", "fact")[0]["content"] == "Fact"
    assert not memory.retrieve("b")
    memory.invalidate("a", item["id"])
    assert not memory.retrieve("a")
    bad = memory.save_candidate("a", "Guess", "model", [], expiry)
    with pytest.raises(ValueError):
        memory.promote("a", bad["id"], "human")
    expired = memory.save_candidate(
        "a",
        "Old",
        "test",
        [{"passed": True, "source": "test"}],
        (datetime.now(UTC) - timedelta(days=1)).isoformat(),
    )
    with pytest.raises(ValueError):
        memory.promote("a", expired["id"], "human")


@pytest.mark.parametrize(
    "path", ["../a.md", "/a.md", "a/../b.md", "a\\b.md", "a.txt", "a//b.md", "./a.md"]
)
def test_path_escape(path):
    """Publication accepts only normalized relative Markdown paths."""
    with pytest.raises(ValueError):
        validate_document_path(path)


def test_document_uncertain_no_retry_receipt_reconcile(tmp_path):
    """A timeout never causes another POST, even across publisher restarts."""
    posts = []

    def transport(request):
        """Simulate a committed request whose first response was lost."""
        assert request.headers["authorization"] == "Bearer fake-secret"
        if request.method == "POST":
            posts.append(json.loads(request.content))
            raise httpx.ReadTimeout("response lost")
        return httpx.Response(
            200,
            json={
                "status": "READY",
                "document_id": "doc-1",
                "project_id": "a",
                "idempotency_key": "key",
                "content_hash": posts[0]["content_hash"],
                "s3_version_id": "v1",
            },
        )

    client = httpx.Client(transport=httpx.MockTransport(transport))
    store = Store(tmp_path / "state.db")
    publisher = MarkdownPublisher(store, "https://example.test", "fake-secret", client)
    assert publisher.publish("a", "r", "docs/a.md", "# Hello", "key")["status"] == "uncertain"
    publisher = MarkdownPublisher(Store(store.path), "https://example.test", "fake-secret", client)
    assert publisher.publish("a", "r", "docs/a.md", "# Hello", "key")["status"] == "uncertain"
    assert len(posts) == 1
    with pytest.raises(ValueError):
        publisher.publish("a", "r", "docs/a.md", "changed", "key")
    with pytest.raises(ValueError):
        publisher.accept_receipt(
            "a", "key", {"status": "READY", "document_id": "wrong", "content_hash": "wrong"}
        )
    assert publisher.reconcile("a", "key")["document_id"] == "doc-1"
    assert publisher.publish("a", "r", "docs/a.md", "# Hello", "key")["status"] == "READY"
    assert b"fake-secret" not in store.path.read_bytes()
    client.close()


def test_scope_tools_and_mcp_allowlists(tmp_path):
    """Denied capabilities cannot dispatch and model inputs cannot override scope."""
    store = Store(tmp_path / "state.db")
    events = EventCollector(store, tmp_path / "logs")
    tools = ScopedTools("a", "r", store, events, MemoryStore(store))
    with pytest.raises(PermissionError):
        tools.call("publish_markdown", {})
    with pytest.raises(ValueError):
        tools.call("retrieve_project_memory", {"project_id": "b"})
    assert {tool.name for tool in tools.langchain_tools()} == {
        "retrieve_project_memory",
        "save_memory_candidate",
        "request_approval",
    }
    with pytest.raises(ValueError):
        MCPTools("https://evil.test", "fake", {"https://trusted.test"}, {}, events, "a", "r")


@pytest.mark.asyncio
async def test_mcp_supported_adapter_scoping_and_redaction(tmp_path):
    """Fake the network boundary while exercising real supported adapter construction."""
    store = Store(tmp_path / "state.db")
    events = EventCollector(store, tmp_path / "logs")
    mcp = MCPTools(
        "https://trusted.test/mcp",
        "fake-secret",
        {"https://trusted.test/mcp"},
        {"research": {"search"}},
        events,
        "a",
        "r",
    )
    calls = []

    class FakeTool:
        """Return untrusted server content after recording the scoped call."""

        name = "search"
        args = ("project_id", "run_id", "query")

        async def ainvoke(self, arguments):
            """Capture injected project scope and simulate a secret-bearing result."""
            calls.append(arguments)
            return {"result": "ok", "access_token": "never-save"}

    class FakeClient:
        """Avoid live authentication and network connections."""

        async def get_tools(self, server_name):
            """Expose one selected remote tool."""
            return [FakeTool()]

    mcp.client = FakeClient()
    with pytest.raises(PermissionError):
        await mcp.call("writer", "search", {})
    with pytest.raises(ValueError):
        await mcp.call("research", "search", {"project_id": "other"})
    result = await mcp.call("research", "search", {"query": "fact"})
    assert result["access_token"] == "[REDACTED]"
    assert calls == [{"query": "fact", "project_id": "a", "run_id": "r"}]
    assert events.replay("a", "r")[0]["agent_id"] == "research"


def test_concurrent_event_sequences(tmp_path):
    """Separate collector instances share one monotonic journal without lost exports."""
    store = Store(tmp_path / "state.db")
    first = EventCollector(store, tmp_path / "logs")
    second = EventCollector(Store(store.path), tmp_path / "logs")
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(
            pool.map(lambda n: (first if n % 2 else second).emit("a", "r", "tick"), range(16))
        )
    assert sorted(item["sequence"] for item in results) == list(range(1, 17))
    assert len(first.replay("a", "r")) == 16
    assert (
        sum(len(path.read_text().splitlines()) for path in (tmp_path / "logs").glob("*.jsonl"))
        == 16
    )


def test_invalid_publication_receipt_stays_uncertain(tmp_path):
    """HTTP success alone cannot establish document delivery."""
    client = httpx.Client(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                201, json={"status": "READY", "document_id": "wrong-revision"}
            )
        )
    )
    publisher = MarkdownPublisher(
        Store(tmp_path / "state.db"), "https://example.test", "fake", client
    )
    assert publisher.publish("a", "r", "a.md", "# A", "k")["status"] == "uncertain"
    client.close()
