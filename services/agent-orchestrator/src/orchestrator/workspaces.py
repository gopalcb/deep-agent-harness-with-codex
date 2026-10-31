"""Resolve logical workspace references; NestJS owns writer admission and leases."""

import hashlib
import json

from orchestrator.contracts import TaskAssignment


def action_digest(task: TaskAssignment) -> str:
    """Bind approval to all immutable dispatch fields, including revision and scope."""
    payload = json.dumps(task.model_dump(), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode()).hexdigest()
