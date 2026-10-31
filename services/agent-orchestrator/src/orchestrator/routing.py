"""Authenticated loopback REST routes over durable workflow operations."""

import hmac

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, StrictBool

from orchestrator.contracts import WorkflowRequest

router = APIRouter(prefix="/v1")


class ApprovalRequest(BaseModel):
    """Require an explicit boolean approval decision with no ignored fields."""

    model_config = ConfigDict(extra="forbid")
    approved: StrictBool


def authenticate(request: Request, authorization: str | None = Header(default=None)) -> None:
    """Reject missing or incorrect internal bearer credentials in constant time."""
    expected = f"Bearer {request.app.state.settings.token}"
    if not authorization or not hmac.compare_digest(authorization, expected):
        raise HTTPException(status_code=401, detail="invalid bearer token")


@router.post("/runs", dependencies=[Depends(authenticate)])
def create_run(payload: WorkflowRequest, request: Request) -> dict:
    """Admit the run durably; the lifespan scheduler advances it in the background."""
    result = request.app.state.workflow.create(payload)
    request.app.state.projects.add(payload.project_id)
    return result


@router.get("/runs/{run_id}", dependencies=[Depends(authenticate)])
def inspect_run(run_id: str, request: Request, project_id: str = "lab") -> dict:
    """Read one run and perform at most one external task reconciliation."""
    workflow = request.app.state.workflow
    run = workflow.inspect(project_id, run_id)
    if run["status"] in {"running", "uncertain", "cancel_requested"}:
        return workflow.advance(project_id, run_id)
    return run


@router.post("/runs/{run_id}/advance", dependencies=[Depends(authenticate)])
def advance_run(run_id: str, request: Request, project_id: str = "lab") -> dict:
    """Advance one bounded scheduling turn."""
    return request.app.state.workflow.advance(project_id, run_id)


@router.post("/runs/{run_id}/approval", dependencies=[Depends(authenticate)])
def approve_run(
    run_id: str, payload: ApprovalRequest, request: Request, project_id: str = "lab"
) -> dict:
    """Record an exact-action decision before any sensitive dispatch."""
    return request.app.state.workflow.approve(project_id, run_id, payload.approved)


@router.post("/runs/{run_id}/cancel", dependencies=[Depends(authenticate)])
def cancel_run(run_id: str, request: Request, project_id: str = "lab") -> dict:
    """Request cancellation and return its confirmed or uncertain state."""
    return request.app.state.workflow.cancel(project_id, run_id)


@router.get("/runs/{run_id}/events", dependencies=[Depends(authenticate)])
def replay_events(
    run_id: str, request: Request, project_id: str = "lab", after: int = Query(default=0, ge=0)
) -> list[dict]:
    """Return one bounded replay page; NestJS owns the browser SSE transport."""
    request.app.state.workflow.inspect(project_id, run_id)
    return request.app.state.workflow.events.replay(project_id, run_id, after=after)
