---
file-group: workflow-docs
project: deep-agent-harness-with-codex-lab
title: Engineering lab ARCHITECTURE
---
# Architecture

The standalone lab adds a Python coordinator and an isolated NestJS Codex boundary without modifying the sibling Runtime Controller. Angular talks only to NestJS; Python calls authenticated internal task endpoints. NestJS alone constructs SDK threads. Existing controller app-server sessions are never attached.

## Execution flow
A validated WorkflowRequest is durably admitted and routed to a direct task or planner-produced DAG. LangGraph checkpoints coordinator transitions. Python writes invocation intent before dispatch and reconciles uncertain tasks by status rather than starting duplicates. NestJS admits tasks and workspace leases in one SQLite transaction, streams the SDK, then runs registered argv checks. Only passed evidence allows graph success. Failed checks permit bounded same-thread repair. Sensitive tasks wait for exact-action approval, but the coding boundary deliberately rejects protected operations without a dedicated approved executor.

## Modules
- `services/agent-orchestrator/src/orchestrator/contracts.py`: Pydantic boundary models.
- `workflow.py`, `planning.py`, `context.py`: graph, deterministic/live planning, context middleware and bounded read-only subagents.
- `storage.py`, `events.py`: scoped SQLite records and deduplicated replay; rotating JSONL derived from SQLite.
- `memory.py`: reviewed, evidenced, expiring project knowledge.
- `integrations.py`, `integration_routes.py`: optional configured services and authenticated, explicitly requested operations; default deny.
- `tools.py`, `documents.py`: scoped coordination/MCP and authenticated publication adapter.
- `codex_client.py`: HTTP execution client, no Python Codex SDK.
- `config.py`, `validation.py`, `workspaces.py`: configuration, DAG validation, action digests.
- `api.py`, `routing.py`: FastAPI lifecycle, background reconciliation and authenticated routes.
- `services/control-plane/src`: strict admission, durable leases, SDK/demo transports, registered checks and HTTP/SSE gateway.
- `apps/lab-ui/src`: request form, task dependencies, approvals and event timeline.

## Configuration and durability
`npm run demo` starts both services with a generated ephemeral internal token and explicit demo transports. State remains in project `.runtime`; token is not printed. Live mode requires explicit server workspace/check configuration and planner credentials. A single Python process and single NestJS owner are the supported local topology; process-wide graph locks do not establish distributed scheduling safety. SQLite keeps graph state and execution state separately. Unresolved restart leases stay held until operator reconciliation; no automatic lease stealing.

## Context and memory
Deep Agents receives an artifact-only backend, planning/research tools, SDK summarization and a model-call 70% guard. Tokens are conservatively estimated, not measured. Codex owns its internal compaction; native agent occupancy is unavailable. Verified workflow outcomes become candidates; promotion is a separate review action. Unreviewed, expired or invalidated memory is excluded from retrieval.

## Extension points and limits
Existing-controller mounting needs transport ownership migration and regression tests; this implementation does not do that migration. PostgreSQL checkpointer dependency is available but the implemented local service uses SQLite. MCP and document adapters require trusted endpoints and matching contracts. Document timeouts remain uncertain until receipt reconciliation. JSONL is a restart-rebuilt export, not a transactional second authority, and currently rebuilds the complete history on append. Parallel writable engineering is not enabled; separate worktrees and merge integration remain future extensions.
