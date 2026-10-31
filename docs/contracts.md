---
file-group: workflow-docs
project: deep-agent-harness-with-codex-lab
title: Engineering lab contracts
---
# Frozen local interfaces

All Python domain methods are synchronous unless explicitly noted. JSON uses snake_case.
Shared Pydantic models live in `contracts.py`; workers must not edit that file without main approval.

## Persistence (worker B)
`Store(path: str | Path)` owns a SQLite DB, creates parent directories, uses thread-safe per-operation connections.
- `put(namespace: str, project_id: str, key: str, value: dict) -> None`
- `get(namespace: str, project_id: str, key: str) -> dict | None`
- `list(namespace: str, project_id: str) -> list[dict]`
- `claim(namespace: str, project_id: str, key: str, payload: dict) -> tuple[dict, bool]`: atomic insert-if-absent; canonical payload conflict raises ValueError; returns stored payload and created flag.
- `close() -> None` if resources require it.
`EventCollector(store: Store, directory: Path)`:
- `append(event: Event | dict) -> dict` returns envelope including sequence, deduplicates event_id and rejects conflicting duplicate.
- `replay(project_id: str, run_id: str, after: int = 0, limit: int = 200) -> list[dict]`
- `emit(project_id: str, run_id: str, event_type: str, metadata: dict | None = None, **fields) -> dict` creates timestamp/event_id and passes envelope through append.
Worker B can add methods for owned memory/doc functionality without changing these interfaces.

## Workflow and HTTP (worker A)
`WorkflowService(store, events, codex, checkpoint_path: str, planner=None)`:
- `create(request: WorkflowRequest) -> dict`: durable admitted run (run_id, project_id, status, tasks, request).
- `advance(project_id: str, run_id: str) -> dict`: advance real durable LangGraph; asynchronous transport tasks may leave running; resume later.
- `inspect(project_id: str, run_id: str) -> dict`
- `approve(project_id: str, run_id: str, approved: bool) -> dict`: bound to current assignment action digest; no dispatch before approval.
- `cancel(project_id: str, run_id: str) -> dict`
`CodexClient(base_url: str, token: str)` synchronous httpx:
`start(task: TaskAssignment) -> TaskResult`, `status(project_id, run_id, task_id) -> TaskResult`, `resume(project_id, run_id, task_id, feedback, idempotency_key) -> TaskResult`, `cancel(project_id, run_id, task_id) -> TaskResult`, `events(project_id, run_id, task_id, after=0) -> list[dict]`.

FastAPI binds 127.0.0.1:8000. All `/v1` routes require Authorization Bearer LAB_INTERNAL_TOKEN. Missing token fails startup. Health can be public.
- POST `/v1/runs` request WorkflowRequest -> run dict
- GET `/v1/runs/{run_id}?project_id=lab` -> run dict
- POST `/v1/runs/{run_id}/advance?project_id=lab` -> run dict
- POST `/v1/runs/{run_id}/approval?project_id=lab` body {approved: bool} -> run dict
- POST `/v1/runs/{run_id}/cancel?project_id=lab` -> run dict
- GET `/v1/runs/{run_id}/events?project_id=lab&after=0` -> JSON event list (NestJS produces browser SSE)
Creation schedules background advancement; GET may reconcile active task progress. Bound loops, never busy-wait.

## NestJS (main)
127.0.0.1:3100. Authenticated `/internal/v1/tasks`: POST assignment, GET `/{task_id}?project_id&run_id`, POST `/{task_id}/resume` body {project_id,run_id,feedback,idempotency_key}, POST `/{task_id}/cancel` body {project_id,run_id}, GET `/{task_id}/events?project_id&run_id&after` -> event list.
Public same-origin `/api/runs` gateway proxies Python and `/api/runs/:run_id/events` is replayable SSE. Demo only loopback browser access, Origin validation, explicit demo banner; live public access requires LAB_BROWSER_TOKEN bearer. Internal token never returned to browser.
NestJS persists admissions + authoritative workspace leases before SDK calls. Interrupted invocations become uncertain and retain leases. Verification uses configured argv check registry. Demo uses disposable fixture, never user repository.
