"""Authenticated explicit document/MCP operations, disabled by default policy."""

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from orchestrator.routing import authenticate

router = APIRouter(prefix="/v1/runs/{run_id}/integrations", dependencies=[Depends(authenticate)])


class Publication(BaseModel):
    """One exact completed document revision requested by the authenticated caller."""

    model_config = ConfigDict(extra="forbid")
    path: str
    content: str = Field(min_length=1, max_length=1_000_000)
    idempotency_key: str = Field(min_length=1, max_length=160)
    metadata: dict = Field(default_factory=dict)


class MCPRequest(BaseModel):
    """A scoped allowlisted MCP call, never a caller-selected endpoint."""

    model_config = ConfigDict(extra="forbid")
    agent_id: str
    name: str
    arguments: dict = Field(default_factory=dict)


@router.post("/documents")
def publish(run_id: str, payload: Publication, request: Request, project_id: str = "lab") -> dict:
    """Publish only with an explicit configured permission and authenticated run scope."""
    try:
        return request.app.state.integrations.publish(project_id, run_id, **payload.model_dump())
    except PermissionError as error:
        raise HTTPException(403, str(error)) from error


@router.post("/documents/{key}/reconcile")
def reconcile(run_id: str, key: str, request: Request, project_id: str = "lab") -> dict:
    """Read back the admitted revision rather than repeating an uncertain write."""
    try:
        return request.app.state.integrations.reconcile(project_id, run_id, key)
    except PermissionError as error:
        raise HTTPException(403, str(error)) from error


@router.get("/documents")
def search(run_id: str, request: Request, q: str = "", project_id: str = "lab") -> list:
    """Search the configured trusted document service in an existing run scope."""
    try:
        return request.app.state.integrations.search(project_id, run_id, q)
    except PermissionError as error:
        raise HTTPException(403, str(error)) from error


@router.post("/mcp")
async def call_mcp(
    run_id: str, payload: MCPRequest, request: Request, project_id: str = "lab"
) -> object:
    """Call an explicitly configured MCP capability with server-bound scope."""
    try:
        return await request.app.state.integrations.mcp_call(
            project_id, run_id, payload.agent_id, payload.name, payload.arguments
        )
    except PermissionError as error:
        raise HTTPException(403, str(error)) from error
