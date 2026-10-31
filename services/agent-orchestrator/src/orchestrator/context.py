"""Enforce configured context headroom inside actual Deep Agents model calls."""

import hashlib
import json
import math
from pathlib import Path

from deepagents.middleware.summarization import SummarizationMiddleware
from langchain.agents.middleware import AgentMiddleware


def count_context_tokens(messages: list) -> int:
    """Conservatively estimate tokens from UTF-8 bytes including tool metadata."""
    payload = [
        message.model_dump(mode="json") if hasattr(message, "model_dump") else message
        for message in messages
    ]
    return math.ceil(len(json.dumps(payload, ensure_ascii=False).encode()) / 2)


class ContextBudgetMiddleware(AgentMiddleware):
    """Recount the final prompt after SDK summarization and reject oversized calls."""

    def __init__(
        self, capacity: int, reserve: int = 4096, events=None, scope: dict | None = None
    ) -> None:
        """Reserve output/headroom before applying the application's 70% policy."""
        if capacity <= reserve or reserve < 0:
            raise ValueError("context capacity must exceed output/headroom reserve")
        self.threshold = int((capacity - reserve) * 0.70)
        self.events, self.scope = events, scope or {}
        self.calls = 0

    def check_request(self, request) -> None:
        """Count system, tools and messages on every actual model invocation."""
        messages = list(request.messages)
        if request.system_message:
            messages.insert(0, request.system_message)
        schemas = []
        for tool in request.tools:
            if isinstance(tool, dict):
                schemas.append(tool)
            else:
                schema = tool.args_schema
                schemas.append(
                    {
                        "name": tool.name,
                        "description": tool.description,
                        "schema": schema.model_json_schema() if schema else {},
                    }
                )
        tokens = count_context_tokens(messages + schemas)
        self.calls += 1
        if self.events and self.scope:
            self.events.emit(
                self.scope["project_id"],
                self.scope["run_id"],
                "context.recounted",
                {
                    "estimated_tokens": tokens,
                    "threshold": self.threshold,
                    "method": "conservative_utf8_bytes_divided_by_two",
                },
                workflow_id=self.scope.get("workflow_id", "planned"),
                agent_id=self.scope.get("agent_id", "deep-planner"),
                node_id="planning",
            )
        if tokens >= self.threshold:
            raise ValueError(
                "context remains at or above 70% after SDK compaction; handoff required"
            )

    def wrap_model_call(self, request, handler):
        """Guard the synchronous model path after SDK compaction/offloading."""
        self.check_request(request)
        return handler(request)

    async def awrap_model_call(self, request, handler):
        """Apply the identical policy to asynchronous model calls."""
        self.check_request(request)
        return await handler(request)


class ObservedSummarizationMiddleware(SummarizationMiddleware):
    """Observe SDK history writes without claiming unobserved compaction events."""

    name = "SummarizationMiddleware"

    def __init__(self, model, backend, history_root, budget, scope: dict, events=None) -> None:
        """Retain the SDK summarizer while observing its scoped history artifacts."""
        super().__init__(
            model=model,
            backend=backend,
            trigger=("tokens", max(100, budget.threshold - 8000)),
            keep=("messages", 2),
            token_counter=count_context_tokens,
            trim_tokens_to_summarize=min(2000, budget.threshold // 4),
        )
        self.history_root, self.events, self.scope = Path(history_root), events, scope

    def snapshot_history(self) -> dict:
        """Fingerprint existing SDK conversation-history files without logging content."""
        return {
            str(path.relative_to(self.history_root)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in self.history_root.glob("*.md")
            if path.is_file() and not path.is_symlink()
        }

    def emit_offloads(self, before: dict) -> None:
        """Emit receipts only for history revisions written during this SDK call."""
        if not self.events:
            return
        for path, digest in self.snapshot_history().items():
            if before.get(path) != digest:
                self.events.emit(
                    self.scope["project_id"],
                    self.scope["run_id"],
                    "context.offloaded",
                    {
                        "artifact": f"/conversation_history/{path}",
                        "sha256": digest,
                        "source": "deepagents-sdk",
                    },
                    workflow_id=self.scope["workflow_id"],
                    agent_id=self.scope.get("agent_id", "deep-planner"),
                    node_id="planning",
                )

    def wrap_model_call(self, request, handler):
        """Observe SDK offload before handing its compacted prompt downstream."""
        before = self.snapshot_history()

        def observe(compacted):
            """Record newly persisted SDK history before the final budget guard."""
            self.emit_offloads(before)
            return handler(compacted)

        return super().wrap_model_call(request, observe)

    async def awrap_model_call(self, request, handler):
        """Observe actual asynchronous SDK history revisions with the same receipts."""
        before = self.snapshot_history()

        async def observe(compacted):
            """Record the actual SDK offload before asynchronous model dispatch."""
            self.emit_offloads(before)
            return await handler(compacted)

        return await super().awrap_model_call(request, observe)
