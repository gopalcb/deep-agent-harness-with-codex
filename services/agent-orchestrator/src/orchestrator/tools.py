"""Expose scoped coordination tools and allowlisted MCP Streamable HTTP calls."""

from urllib.parse import urlsplit

import httpx
from langchain_core.tools import StructuredTool
from langchain_mcp_adapters.client import MultiServerMCPClient

from orchestrator.contracts import TaskAssignment
from orchestrator.events import redact


class ScopedTools:
    """Bind model tools to trusted project/run identity and explicit permissions."""

    def __init__(
        self,
        project_id: str,
        run_id: str,
        store: object,
        events: object,
        memory: object,
        codex: object = None,
        publisher: object = None,
        permissions: set[str] | None = None,
    ):
        """Keep identity and service boundaries outside model supplied arguments."""
        self.project_id, self.run_id = project_id, run_id
        self.store, self.events, self.memory = store, events, memory
        self.codex, self.publisher = codex, publisher
        self.permissions = (
            permissions
            if permissions is not None
            else {
                "retrieve_project_memory",
                "save_memory_candidate",
                "request_approval",
            }
        )

    def call(self, name: str, arguments: dict) -> object:
        """Audit and dispatch one explicitly permitted coordination capability."""
        if name not in self.permissions:
            raise PermissionError(f"tool denied: {name}")
        if {"project_id", "run_id"} & arguments.keys():
            raise ValueError("scope is bound by the server")
        self.events.emit(
            self.project_id,
            self.run_id,
            "tool.called",
            {"tool": name, "arguments": redact(arguments)},
        )
        if name == "retrieve_project_memory":
            return self.memory.retrieve(self.project_id, **arguments)
        if name == "save_memory_candidate":
            return self.memory.save_candidate(self.project_id, **arguments)
        if name == "get_codex_status" and self.codex:
            return self.codex.status(self.project_id, self.run_id, arguments["task_id"])
        if name == "invoke_codex_task" and self.codex:
            assignment = self.store.get(
                "approved_assignments", self.project_id, arguments["task_id"]
            )
            if not assignment or assignment["run_id"] != self.run_id:
                raise PermissionError("assignment has no matching workflow approval")
            return self.codex.start(TaskAssignment.model_validate(assignment))
        if name == "publish_markdown" and self.publisher:
            return self.publisher.publish(self.project_id, self.run_id, **arguments)
        if name == "search_documents" and self.publisher:
            return self.publisher.search(self.project_id, **arguments)
        if name == "request_approval":
            return self.events.emit(
                self.project_id,
                self.run_id,
                "approval.requested",
                arguments,
                status="waiting_approval",
            )
        raise ValueError("unknown tool or unconfigured boundary")

    def langchain_tools(self) -> list[StructuredTool]:
        """Expose planning-safe wrappers without repository edits or shell access."""

        def retrieve_project_memory(query: str = "", limit: int = 10) -> list:
            """Retrieve reviewed current facts for this project."""
            return self.call("retrieve_project_memory", {"query": query, "limit": limit})

        def save_memory_candidate(
            content: str, source: str, evidence: list[dict], expires_at: str
        ) -> dict:
            """Save an unverified candidate for subsequent explicit review."""
            return self.call(
                "save_memory_candidate",
                {
                    "content": content,
                    "source": source,
                    "evidence": evidence,
                    "expires_at": expires_at,
                },
            )

        def request_approval(reason: str) -> dict:
            """Request approval without granting it."""
            return self.call("request_approval", {"reason": reason})

        def get_codex_status(task_id: str) -> object:
            """Read one Codex task status in this project/run."""
            return self.call("get_codex_status", {"task_id": task_id})

        def search_documents(query: str) -> list:
            """Search documents scoped to this project."""
            return self.call("search_documents", {"query": query})

        def publish_markdown(
            path: str, content: str, idempotency_key: str, metadata: dict | None = None
        ) -> dict:
            """Publish an explicitly permitted completed Markdown revision."""
            return self.call(
                "publish_markdown",
                {
                    "path": path,
                    "content": content,
                    "idempotency_key": idempotency_key,
                    "metadata": metadata,
                },
            )

        wrappers = [retrieve_project_memory, save_memory_candidate, request_approval]
        if self.codex is not None:
            wrappers.append(get_codex_status)
        if self.publisher is not None:
            wrappers.extend([search_documents, publish_markdown])
        return [
            StructuredTool.from_function(function)
            for function in wrappers
            if function.__name__ in self.permissions
        ]


def mcp_http_client(
    headers: dict | None = None, timeout: object = None, auth: object = None
) -> httpx.AsyncClient:
    """Disallow credential-bearing redirect requests from the trusted MCP endpoint."""
    return httpx.AsyncClient(
        headers=headers, timeout=timeout or 20, auth=auth, follow_redirects=False
    )


class MCPTools:
    """Use a real supported adapter with exact endpoint and per-agent tool allowlists."""

    def __init__(
        self,
        url: str,
        token: str,
        allowed_urls: set[str],
        agent_tools: dict[str, set[str]],
        events: object,
        project_id: str,
        run_id: str,
    ):
        """Require authenticated HTTPS and refuse arbitrary transports or endpoints."""
        parsed = urlsplit(url)
        if (
            url not in allowed_urls
            or parsed.scheme != "https"
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
            or not token.strip()
            or not parsed.hostname
        ):
            raise ValueError("MCP requires an authenticated allowlisted HTTPS endpoint")
        self.client = MultiServerMCPClient(
            {
                "trusted": {
                    "transport": "streamable_http",
                    "url": url,
                    "headers": {"Authorization": f"Bearer {token}"},
                    "httpx_client_factory": mcp_http_client,
                }
            },
            handle_tool_errors=False,
        )
        self.agent_tools, self.events = agent_tools, events
        self.project_id, self.run_id = project_id, run_id

    async def call(self, agent_id: str, name: str, arguments: dict) -> object:
        """Invoke an allowed tool using trusted scope and redact its untrusted response."""
        if name not in self.agent_tools.get(agent_id, set()):
            raise PermissionError("MCP tool denied for this agent")
        if {"project_id", "run_id"} & arguments.keys():
            raise ValueError("MCP scope is server-bound")
        tools = await self.client.get_tools(server_name="trusted")
        selected = next((tool for tool in tools if tool.name == name), None)
        if selected is None:
            raise ValueError("allowlisted MCP tool is unavailable")
        if not {"project_id", "run_id"}.issubset(selected.args):
            raise ValueError("MCP tool contract does not accept required scope")
        self.events.emit(
            self.project_id,
            self.run_id,
            "tool.called",
            {"source": "mcp", "tool": name, "arguments": redact(arguments)},
            agent_id=agent_id,
        )
        return redact(
            await selected.ainvoke(
                {**arguments, "project_id": self.project_id, "run_id": self.run_id}
            )
        )
