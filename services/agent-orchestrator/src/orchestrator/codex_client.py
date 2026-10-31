"""Authenticated HTTP transport to NestJS, the only Codex SDK owner."""

from urllib.parse import quote

import httpx

from orchestrator.contracts import TaskAssignment, TaskResult


class CodexClient:
    """Send scoped idempotent operations without retrying uncertain writes."""

    def __init__(self, base_url: str, token: str, transport=None) -> None:
        """Create a bounded authenticated client; transport permits offline fixtures."""
        if not token:
            raise ValueError("LAB_INTERNAL_TOKEN is required")
        self.client = httpx.Client(
            base_url=base_url.rstrip("/"),
            timeout=30,
            headers={"Authorization": f"Bearer {token}"},
            transport=transport,
        )

    def start(self, task: TaskAssignment) -> TaskResult:
        """Admit one durable task through the authoritative workspace boundary."""
        response = self.client.post("/internal/v1/tasks", json=task.model_dump())
        response.raise_for_status()
        return TaskResult.model_validate(response.json())

    def status(self, project_id: str, run_id: str, task_id: str) -> TaskResult:
        """Reconcile a previously admitted or uncertain invocation."""
        response = self.client.get(
            f"/internal/v1/tasks/{quote(task_id, safe='')}",
            params={"project_id": project_id, "run_id": run_id},
        )
        response.raise_for_status()
        return TaskResult.model_validate(response.json())

    def resume(
        self, project_id: str, run_id: str, task_id: str, feedback: str, idempotency_key: str
    ) -> TaskResult:
        """Resume an existing task once for a particular repair revision."""
        response = self.client.post(
            f"/internal/v1/tasks/{quote(task_id, safe='')}/resume",
            json={
                "project_id": project_id,
                "run_id": run_id,
                "feedback": feedback,
                "idempotency_key": idempotency_key,
            },
        )
        response.raise_for_status()
        return TaskResult.model_validate(response.json())

    def cancel(self, project_id: str, run_id: str, task_id: str) -> TaskResult:
        """Request cancellation; confirmation must come from the SDK owner."""
        response = self.client.post(
            f"/internal/v1/tasks/{quote(task_id, safe='')}/cancel",
            json={"project_id": project_id, "run_id": run_id},
        )
        response.raise_for_status()
        return TaskResult.model_validate(response.json())

    def events(self, project_id: str, run_id: str, task_id: str, after: int = 0) -> list[dict]:
        """Fetch one bounded event page for correlation and replay."""
        response = self.client.get(
            f"/internal/v1/tasks/{quote(task_id, safe='')}/events",
            params={"project_id": project_id, "run_id": run_id, "after": after},
        )
        response.raise_for_status()
        return response.json()

    def close(self) -> None:
        """Close pooled network connections."""
        self.client.close()
