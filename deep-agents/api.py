"""Optional standalone HTTP classifier; separate from the Codex-first fallback.

How it is started:
    ../.venv/bin/python -m uvicorn api:app --app-dir deep-agents --port 8000
    Uvicorn imports the module-level app, constructed by create_app(). Tests or
    embedding callers can instead inject a PromptRouter and token into create_app().

Entry points:
    POST /v1/route calls route_prompt() after authenticate() verifies the internal
    bearer. GET /health calls health() without exposing model or token settings.
    route_prompt() passes the prompt to routing.PromptRouter.route() and returns
    the validated question/implementation decision.

Pseudocode:
    construct router using LAB_ROUTER_MODEL when configured
    receive prompt -> verify bearer -> validate request -> classify -> return route

This service never starts Codex, writes repository files or runs the fallback graph.
The main codex/api.py path currently bypasses this optional service entirely.
"""

import hmac
import os

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from routing import PromptRouter, RouteDecision


class PromptRequest(BaseModel):
    """Validate the only input accepted by the routing service."""

    model_config = ConfigDict(extra="forbid")
    prompt: str = Field(min_length=1, max_length=32000)


# Keep the optional classifier endpoint private to callers with the shared bearer.
def authenticate(request: Request, authorization: str | None = Header(default=None)) -> None:
    """Require the control plane's internal bearer token."""
    token = request.app.state.token
    expected = f"Bearer {token}"

    if not token or not authorization or not hmac.compare_digest(authorization, expected):
        raise HTTPException(status_code=401, detail="invalid bearer token")


# Construct the standalone classifier; the Codex-first fallback path bypasses it.
# Dependency injection permits local checks without model credentials.
def create_app(router: PromptRouter | None = None, token: str | None = None) -> FastAPI:
    """Build the small routing service with injectable test dependencies."""
    app = FastAPI(title="Deep Agent prompt router")

    app.state.token = token if token is not None else os.environ.get("LAB_INTERNAL_TOKEN", "")
    app.state.router = router or PromptRouter(os.environ.get("LAB_ROUTER_MODEL"))

    # Public health reports only service liveness.
    @app.get("/health")
    def health() -> dict:
        """Return public liveness without configuration details."""
        return {"status": "ok"}

    # Classify the request without starting Codex or granting filesystem permissions.
    @app.post("/v1/route", dependencies=[Depends(authenticate)])
    def route_prompt(payload: PromptRequest, request: Request) -> RouteDecision:
        """Classify one prompt without planning or executing it."""
        return request.app.state.router.route(payload.prompt)

    return app


app = create_app()
