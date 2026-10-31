"""Construct optional authenticated integrations and gate explicit scoped API actions.

No network requests occur during configuration. HTTP route authentication belongs
to the API; these operations additionally require configured capability permission
and an existing project/run pair. They are never called automatically by workflow.
"""

import json
import os

from orchestrator.documents import MarkdownPublisher
from orchestrator.events import EventCollector
from orchestrator.storage import Store
from orchestrator.tools import MCPTools

CAPABILITIES = {"publish_markdown", "reconcile_markdown", "search_documents", "mcp_call"}


class IntegrationServices:
    """Hold optional boundaries without enabling implicit external side effects."""

    def __init__(
        self,
        store: Store,
        events: EventCollector,
        permissions: set[str],
        publisher: MarkdownPublisher | None = None,
        mcp_config: dict | None = None,
    ):
        """Bind durable scope and externally configured capability permissions."""
        self.store, self.events, self.permissions = store, events, permissions
        self.publisher, self.mcp_config = publisher, mcp_config

    @classmethod
    def from_env(
        cls, store: Store, events: EventCollector, environ: dict | None = None
    ) -> "IntegrationServices":
        """Load optional credentials without logging, persisting or contacting endpoints."""
        config = os.environ if environ is None else environ
        permissions = {
            item.strip()
            for item in config.get("LAB_INTEGRATION_PERMISSIONS", "").split(",")
            if item.strip()
        }
        if permissions - CAPABILITIES:
            raise ValueError("unknown integration capability permission")
        document_url, document_token = (
            config.get("LAB_DOCUMENT_URL", ""),
            config.get("LAB_DOCUMENT_TOKEN", ""),
        )
        mcp_url, mcp_token = config.get("LAB_MCP_URL", ""), config.get("LAB_MCP_TOKEN", "")
        if bool(document_url) != bool(document_token) or bool(mcp_url) != bool(mcp_token):
            raise ValueError("integration endpoint and authentication must be configured together")
        mcp_config = None
        if mcp_url:
            try:
                allowlist = json.loads(config.get("LAB_MCP_TOOLS", "{}"))
            except (TypeError, json.JSONDecodeError) as error:
                raise ValueError(
                    "LAB_MCP_TOOLS must be an agent to tool-list JSON object"
                ) from error
            if not isinstance(allowlist, dict) or any(
                not isinstance(agent, str)
                or not isinstance(names, list)
                or any(not isinstance(name, str) or not name.strip() for name in names)
                for agent, names in allowlist.items()
            ):
                raise ValueError("LAB_MCP_TOOLS must be an agent to tool-list JSON object")
            mcp_config = {
                "url": mcp_url,
                "token": mcp_token,
                "allowed_urls": {mcp_url},
                "agent_tools": {agent: set(names) for agent, names in allowlist.items()},
            }
            # The real supported adapter validates endpoint policy without opening a session.
            MCPTools(
                **mcp_config, events=events, project_id="configuration", run_id="configuration"
            )
        publisher = MarkdownPublisher(store, document_url, document_token) if document_url else None
        return cls(store, events, permissions, publisher, mcp_config)

    def authorize(self, capability: str, project_id: str, run_id: str) -> None:
        """Require a configured operation and an existing run in the supplied project."""
        if capability not in self.permissions:
            raise PermissionError("integration capability denied")
        if self.store.get("runs", project_id, run_id) is None:
            raise KeyError("scoped run not found")

    def publish(
        self,
        project_id: str,
        run_id: str,
        path: str,
        content: str,
        idempotency_key: str,
        metadata: dict | None = None,
    ) -> dict:
        """Publish only an explicit authenticated API request to an authorized run."""
        self.authorize("publish_markdown", project_id, run_id)
        if self.publisher is None:
            raise ValueError("document integration is not configured")
        self.events.emit(
            project_id, run_id, "tool.called", {"tool": "publish_markdown", "path": path}
        )
        return self.publisher.publish(project_id, run_id, path, content, idempotency_key, metadata)

    def reconcile(self, project_id: str, run_id: str, idempotency_key: str) -> dict:
        """Reconcile only an admission belonging to this exact project and run."""
        self.authorize("reconcile_markdown", project_id, run_id)
        admission = self.store.get("document_admissions", project_id, idempotency_key)
        if not admission or admission["run_id"] != run_id:
            raise KeyError("scoped document admission not found")
        if self.publisher is None:
            raise ValueError("document integration is not configured")
        self.events.emit(project_id, run_id, "tool.called", {"tool": "reconcile_markdown"})
        return self.publisher.reconcile(project_id, idempotency_key)

    def search(self, project_id: str, run_id: str, query: str) -> list[dict]:
        """Search the configured document contract within an authorized project."""
        self.authorize("search_documents", project_id, run_id)
        if self.publisher is None:
            raise ValueError("document integration is not configured")
        self.events.emit(project_id, run_id, "tool.called", {"tool": "search_documents"})
        return self.publisher.search(project_id, query)

    async def mcp_call(
        self, project_id: str, run_id: str, agent_id: str, name: str, arguments: dict
    ) -> object:
        """Invoke an explicit per-agent allowlisted MCP action with immutable scope."""
        self.authorize("mcp_call", project_id, run_id)
        if self.mcp_config is None:
            raise ValueError("MCP integration is not configured")
        adapter = MCPTools(
            **self.mcp_config, events=self.events, project_id=project_id, run_id=run_id
        )
        return await adapter.call(agent_id, name, arguments)

    def close(self) -> None:
        """Release the configured owned document HTTP client at service shutdown."""
        if self.publisher:
            self.publisher.close()
