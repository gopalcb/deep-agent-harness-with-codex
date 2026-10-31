"""Verify real SDK agent tool isolation and middleware without provider credentials."""

import pytest
from deepagents.backends import FilesystemBackend
from langchain.agents.middleware.types import ModelRequest
from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from orchestrator.context import ContextBudgetMiddleware
from orchestrator.contracts import WorkflowRequest
from orchestrator.planning import DeepPlanner


class PlanningModel(FakeMessagesListChatModel):
    """Support tool binding while retaining deterministic local model responses."""

    def bind_tools(self, tools, **kwargs):
        """Use the SDK's actual structured-response flow without a network model."""
        return self


def test_deep_agent_real_model_call_and_scoped_tools(tmp_path):
    """A real Deep Agent reaches the fake model through the installed budget middleware."""
    model = PlanningModel(
        responses=[
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "PlanOutput",
                        "args": {"tasks": [{"task_id": "api", "instruction": "Implement API"}]},
                        "id": "plan-1",
                        "type": "tool_call",
                    }
                ],
            )
        ]
    )
    planner = DeepPlanner(model, tmp_path, capacity=100000)
    tasks = planner.plan(
        WorkflowRequest(
            project_id="lab", instruction="Change API", workflow_id="planned", idempotency_key="one"
        ),
        "run",
    )
    assert [task.task_id for task in tasks] == ["api"]
    assert planner.last_budget.calls == 1
    assert (tmp_path / "lab" / "run").is_dir()
    node = planner.last_agent.nodes["tools"]
    tool_names = set(node.bound.tools_by_name)
    assert "execute" not in tool_names
    assert {"read_file", "write_file", "task"} <= tool_names
    assert not (tmp_path / "escape.txt").exists()


def test_context_guard_blocks_actual_oversized_model_call(tmp_path):
    """System/tool overhead is counted and oversized requests never reach the model."""
    model = PlanningModel(responses=[AIMessage(content="unused")])
    planner = DeepPlanner(model, tmp_path, capacity=5000)
    agent = planner.build_agent("lab", "run")
    with pytest.raises(ValueError, match="70%"):
        agent.invoke({"messages": [HumanMessage(content="Small request")]})
    assert planner.last_budget.calls == 1


def test_context_guard_includes_system_and_tools():
    """A short user message cannot bypass a large system prompt."""
    budget = ContextBudgetMiddleware(1000, reserve=100)
    model = PlanningModel(responses=[AIMessage(content="unused")])
    request = ModelRequest(
        model=model,
        messages=[HumanMessage(content="hi")],
        system_message=SystemMessage(content="x" * 3000),
        tools=[],
    )
    with pytest.raises(ValueError, match="70%"):
        budget.wrap_model_call(request, lambda request: AIMessage(content="should never run"))


def test_artifact_backend_blocks_path_escape(tmp_path):
    """Installed FilesystemBackend enforces the virtual planning artifact root."""
    backend = FilesystemBackend(root_dir=tmp_path / "lab" / "run", virtual_mode=True)
    with pytest.raises(ValueError, match="traversal"):
        backend.write("/../../../escape.txt", "escape")
    assert not (tmp_path / "escape.txt").exists()


def test_sdk_summarizes_and_offloads_before_guard(tmp_path):
    """SDK compaction persists history and the real model call receives bounded context."""
    model = PlanningModel(
        responses=[
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "PlanOutput",
                        "args": {"tasks": [{"task_id": "api", "instruction": "Implement API"}]},
                        "id": "plan-after-summary",
                        "type": "tool_call",
                    }
                ],
            )
        ]
    )
    planner = DeepPlanner(model, tmp_path, capacity=50000)
    agent = planner.build_agent("lab", "run")
    messages = [
        HumanMessage(content=f"Historical context {index}: " + "x" * 14000) for index in range(6)
    ]
    result = agent.invoke({"messages": messages}, {"recursion_limit": 10})
    assert result["structured_response"].tasks[0].task_id == "api"
    assert planner.last_budget.calls == 1
    assert list((tmp_path / "lab" / "run" / "conversation_history").glob("*.md"))


def test_actual_skill_loader_and_scoped_tool_events(tmp_path):
    """The installed loader injects staged skill metadata into real model calls."""
    from langchain_core.callbacks import BaseCallbackHandler

    from orchestrator.events import EventCollector
    from orchestrator.storage import Store

    class CapturePrompts(BaseCallbackHandler):
        """Observe model inputs locally without a provider or runtime logging."""

        def __init__(self) -> None:
            """Keep captured messages only inside this disposable assertion."""
            self.prompts = []

        def on_chat_model_start(self, serialized, messages, **kwargs) -> None:
            """Capture the actual final system prompts, including loader output."""
            self.prompts.extend(str(message.content) for batch in messages for message in batch)

    capture = CapturePrompts()
    model = PlanningModel(
        responses=[
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "retrieve_project_memory",
                        "args": {},
                        "id": "memory",
                        "type": "tool_call",
                    }
                ],
            ),
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "PlanOutput",
                        "args": {"tasks": [{"task_id": "api", "instruction": "Implement API"}]},
                        "id": "plan",
                        "type": "tool_call",
                    }
                ],
            ),
        ],
        callbacks=[capture],
    )
    store = Store(tmp_path / "records.sqlite")
    events = EventCollector(store, tmp_path / "events")
    planner = DeepPlanner(
        model, tmp_path / "artifacts", capacity=100000, events=events, store=store
    )
    planner.plan(
        WorkflowRequest(
            project_id="lab",
            instruction="Plan scoped work",
            workflow_id="planned",
            idempotency_key="one",
        ),
        "run",
    )
    assert any(
        "scoped-research" in prompt and "scoped-documentation" in prompt
        for prompt in capture.prompts
    )
    assert (tmp_path / "artifacts/lab/run/skills/research/SKILL.md").is_file()
    assert all(event["workflow_id"] == "planned" for event in events.replay("lab", "run"))
    assert any(event["event_type"] == "tool.called" for event in events.replay("lab", "run"))
    assert not any(
        event["event_type"] == "context.offloaded" for event in events.replay("lab", "run")
    )


def test_offload_event_requires_observed_sdk_history_write(tmp_path):
    """The SDK's actual persisted history produces a scoped digest receipt."""
    from orchestrator.events import EventCollector
    from orchestrator.storage import Store

    store = Store(tmp_path / "records.sqlite")
    events = EventCollector(store, tmp_path / "events")
    model = PlanningModel(
        responses=[
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "PlanOutput",
                        "args": {"tasks": [{"task_id": "api", "instruction": "do"}]},
                        "id": "plan",
                        "type": "tool_call",
                    }
                ],
            )
        ]
    )
    planner = DeepPlanner(model, tmp_path / "artifacts", capacity=50000, events=events)
    agent = planner.build_agent("lab", "run")
    agent.invoke(
        {"messages": [HumanMessage(content="history " + "x" * 14000) for unused in range(6)]}
    )
    offloads = [
        event for event in events.replay("lab", "run") if event["event_type"] == "context.offloaded"
    ]
    assert len(offloads) == 1
    assert offloads[0]["workflow_id"] == "planned"
    receipt = offloads[0]["metadata"]
    artifact = tmp_path / "artifacts/lab/run" / receipt["artifact"].lstrip("/")
    import hashlib

    assert receipt["sha256"] == hashlib.sha256(artifact.read_bytes()).hexdigest()
