"""Classify prompts for the optional standalone routing API.

Entry point and caller:
    deep-agents/api.py constructs PromptRouter and calls its route(prompt) method.
    There is no standalone main() function or server in this file. This classifier
    is not invoked by the Codex quota fallback graph in workflow.py.

How it works:
    __init__() constructs a Deep Agent when a model identifier is supplied. It
    disables filesystem tools and the general-purpose subagent because classification
    only needs the prompt. A supplied agent object supports dependency injection.
    route() invokes the agent and validates its structured RouteDecision response.
    Without an agent, route_demo() uses explicit keyword rules for local examples.

Pseudocode:
    create router(model or injected agent)
    reject blank prompt
    if agent exists:
        classify prompt -> validate question/implementation label
    otherwise:
        select label using demo change-verb rules
    return RouteDecision

Demo matching is not model reasoning. A route is a classification recommendation,
not permission to edit files. Execution policy belongs to the calling application.
"""

import re
from typing import Literal

from deepagents import (
    GeneralPurposeSubagentProfile,
    HarnessProfile,
    create_deep_agent,
    register_harness_profile,
)
from pydantic import BaseModel, ConfigDict


class RouteDecision(BaseModel):
    """Return the only decision Python owns."""

    model_config = ConfigDict(extra="forbid")
    route: Literal["question", "implementation"]


class PromptRouter:
    """Choose a Codex access route without owning the Codex workflow."""

    # Build a classification-only Deep Agent when a model is supplied.
    # Disable filesystem tools and delegation because routing needs neither.
    def __init__(self, model: str | None = None, agent=None) -> None:
        """Create a live Deep Agent when a model is configured."""
        self.agent = agent

        if self.agent is None and model:
            register_harness_profile(
                model,
                HarnessProfile(
                    excluded_tools=frozenset(
                        {
                            "edit_file",
                            "execute",
                            "glob",
                            "grep",
                            "ls",
                            "read_file",
                            "write_file",
                            "write_todos",
                        }
                    ),
                    general_purpose_subagent=GeneralPurposeSubagentProfile(enabled=False),
                ),
            )

            self.agent = create_deep_agent(
                model=model,
                tools=[],
                response_format=RouteDecision,
                system_prompt=(
                    "Classify the user's complete prompt only. Return question when Codex should "
                    "answer, explain, inspect, diagnose, or review without changing files. Return "
                    "implementation when the user asks Codex to create, edit, fix, refactor, remove, "
                    "build, or otherwise change files. Do not plan, execute tools, or rewrite the prompt."
                ),
            )

    # Validate the classification result against the two permitted route labels.
    # Without a configured agent, use the explicitly labeled local demo rules.
    def route(self, prompt: str) -> RouteDecision:
        """Return a structured route while leaving the prompt unchanged."""
        normalized = prompt.strip()
        if not normalized:
            raise ValueError("prompt must not be blank")

        if self.agent is None:
            return RouteDecision(route=self.route_demo(normalized))

        result = self.agent.invoke({"messages": [{"role": "user", "content": normalized}]})

        return RouteDecision.model_validate(result["structured_response"])

    # Demonstrate routing without credentials; keyword matching is not model reasoning.
    def route_demo(self, prompt: str) -> Literal["question", "implementation"]:
        """Classify common change verbs locally for the credential-free demo."""
        change_pattern = (
            r"\b(add|build|change|create|delete|edit|fix|implement|make|migrate|move|"
            r"refactor|remove|rename|replace|simplify|update|write)\b"
        )

        return "implementation" if re.search(change_pattern, prompt, re.IGNORECASE) else "question"
