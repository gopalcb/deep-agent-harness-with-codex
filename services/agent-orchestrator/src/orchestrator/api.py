"""Construct the FastAPI service and own bounded background reconciliation."""

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from orchestrator.codex_client import CodexClient
from orchestrator.config import load_settings
from orchestrator.events import EventCollector
from orchestrator.integration_routes import router as integration_router
from orchestrator.integrations import IntegrationServices
from orchestrator.planning import DeepPlanner, DemoPlanner
from orchestrator.routing import router
from orchestrator.storage import Store
from orchestrator.workflow import TERMINAL, WorkflowService

logger = logging.getLogger(__name__)


async def advance_active_round(app: FastAPI, cursors: dict) -> None:
    """Advance at most 100 eligible runs per project, rotating fairly by run ID."""
    for project_id in sorted(app.state.projects):
        runs = await asyncio.to_thread(app.state.workflow.store.list, "runs", project_id)
        active = sorted(
            (
                run
                for run in runs
                if any(item.get("event_replay_pending") for item in run.get("tasks", []))
                or run["status"] not in TERMINAL | {"waiting_approval"}
            ),
            key=lambda run: run["run_id"],
        )
        cursor = cursors.get(project_id, "")
        ordered = [run for run in active if run["run_id"] > cursor] + [
            run for run in active if run["run_id"] <= cursor
        ]
        for run in ordered[:100]:
            cursors[project_id] = run["run_id"]
            try:
                await asyncio.to_thread(app.state.workflow.advance, project_id, run["run_id"])
            except Exception as error:  # noqa: BLE001 - preserve scheduler after isolated run failure
                logger.error("Background advancement failed: %s", type(error).__name__)
                app.state.workflow.events.emit(
                    project_id,
                    run["run_id"],
                    "workflow.error",
                    {"error_type": type(error).__name__},
                )


async def advance_active_runs(app: FastAPI) -> None:
    """Run fair bounded rounds at one-second intervals outside the event loop."""
    cursors = {}
    while True:
        await advance_active_round(app, cursors)
        await asyncio.sleep(1)


def create_app(workflow=None, settings=None) -> FastAPI:
    """Support disposable offline services while enforcing production startup auth."""

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        """Open service resources, resume known runs, then close owned connections."""
        config = settings or load_settings()
        if not config.token:
            raise ValueError("LAB_INTERNAL_TOKEN is required")
        app.state.settings = config
        app.state.projects = {config.project_id}
        owned = workflow is None
        if owned:
            config.data_dir.mkdir(parents=True, exist_ok=True)
            store = Store(config.data_dir / "records.sqlite")
            events = EventCollector(store, config.data_dir / "events")
            codex = CodexClient(config.codex_url, config.token)
            if config.mode == "demo":
                planner = DemoPlanner()
            elif config.model:
                planner = DeepPlanner(
                    config.model,
                    config.data_dir / "planning-artifacts",
                    config.context_capacity,
                    events,
                    store=store,
                )
            else:
                raise ValueError("live mode requires LAB_PLANNER_MODEL")
            service = WorkflowService(
                store, events, codex, str(config.data_dir / "checkpoints.sqlite"), planner
            )
            if isinstance(planner, DeepPlanner):
                planner.checkpointer = service.checkpointer
        else:
            service = workflow
        app.state.workflow = service
        app.state.integrations = IntegrationServices.from_env(service.store, service.events)
        task = asyncio.create_task(advance_active_runs(app))
        try:
            yield
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            # to_thread cannot be force-cancelled. Serializing close behind the
            # graph lock lets an in-flight bounded HTTP call finish first.
            app.state.integrations.close()
            if owned:
                await asyncio.to_thread(close_service, service)

    app = FastAPI(title="Codex-first engineering lab", lifespan=lifespan)
    app.include_router(router)
    app.include_router(integration_router)
    app.add_exception_handler(KeyError, not_found)
    app.add_exception_handler(ValueError, conflict)
    app.get("/health")(health)
    return app


def close_service(service: WorkflowService) -> None:
    """Wait for any graph turn before closing owned transport and persistence."""
    with service.lock:
        service.codex.close()
        service.close()
        service.store.close()


async def not_found(request: Request, error: KeyError) -> JSONResponse:
    """Translate missing scoped records without leaking foreign project details."""
    return JSONResponse(status_code=404, content={"detail": "run not found"})


async def conflict(request: Request, error: ValueError) -> JSONResponse:
    """Return a bounded validation or idempotency conflict response."""
    return JSONResponse(status_code=409, content={"detail": str(error)[:300]})


def health() -> dict:
    """Expose public liveness without configuration or credentials."""
    return {"status": "ok"}


app = create_app()
