"""Shared validated transport models for graph, tools and the NestJS boundary."""
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

Identifier = str
Status = Literal["pending", "running", "waiting_approval", "succeeded", "failed", "cancel_requested", "cancelled", "uncertain", "blocked"]

class StrictModel(BaseModel):
    """Reject unknown transport fields."""
    model_config = ConfigDict(extra="forbid")

class TaskAssignment(StrictModel):
    """One scoped engineering assignment; checks are registered identifiers."""
    project_id: str = Field(pattern=r"^[a-zA-Z0-9_-]{1,80}$")
    run_id: str = Field(pattern=r"^[a-zA-Z0-9_-]{1,80}$")
    task_id: str = Field(pattern=r"^[a-zA-Z0-9_-]{1,80}$")
    role: str = "backend"
    workspace_ref: str = "default"
    instruction: str = Field(min_length=1, max_length=32000)
    context_refs: list[str] = Field(default_factory=list)
    depends_on: list[str] = Field(default_factory=list)
    checks: list[str] = Field(default_factory=lambda: ["fixture"])
    risk: Literal["workspace-write", "read-only", "sensitive"] = "workspace-write"
    revision: int = Field(default=1, ge=1)
    idempotency_key: str = Field(min_length=1, max_length=160)

class TaskResult(StrictModel):
    """Execution state with explicit independent check evidence."""
    project_id: str
    run_id: str
    task_id: str
    status: Status
    thread_id: str | None = None
    artifacts: list[str] = Field(default_factory=list)
    checks: list[dict] = Field(default_factory=list)
    error: str | None = None
    usage: dict = Field(default_factory=dict)

class WorkflowRequest(StrictModel):
    """Public request; workspace and commands are resolved by server policy."""
    project_id: str = Field(pattern=r"^[a-zA-Z0-9_-]{1,80}$")
    instruction: str = Field(min_length=1, max_length=32000)
    workflow_id: Literal["direct", "planned"] = "direct"
    idempotency_key: str = Field(min_length=1, max_length=160)
    visual_target: dict | None = None
    risk: Literal["workspace-write", "read-only", "sensitive"] = "workspace-write"

class Event(StrictModel):
    """Correlated event; SQLite collector assigns the replay sequence."""
    event_id: str
    project_id: str
    run_id: str
    workflow_id: str = "direct"
    node_id: str = "coordinator"
    agent_id: str = "coordinator"
    codex_thread_id: str | None = None
    parent_event_id: str | None = None
    timestamp: str
    event_type: str
    duration_ms: float = 0
    status: str = "running"
    metadata: dict = Field(default_factory=dict)
