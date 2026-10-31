---
file-group: workflow-docs
project: deep-agent-harness-with-codex-lab
title: Engineering lab README
---
# Codex-first engineering lab

A runnable, credential-free local lab for durable LangGraph engineering workflows, a NestJS-owned Codex SDK boundary, Deep Agents planning, scoped memory and a live Angular timeline.

## Run locally

Requires Node 22.13+ and uv (Python 3.11+).

```sh
npm ci
uv sync --locked --project services/agent-orchestrator
npm run build
npm run demo
```

Open http://127.0.0.1:3100. Ctrl+C stops both owned services. Demo mode never calls a model: it writes a disposable fixture under `.runtime/workspace` and runs a real registered Node check. Both direct and planned templates exercise the HTTP orchestration path. Data and checkpoints survive restarts. The internal bearer is generated in memory per launch; no API key is needed.

## Verify

```sh
npm test
npm run test:integration
uv run --project services/agent-orchestrator pytest services/agent-orchestrator/tests -q
uv run --project services/agent-orchestrator ruff check services/agent-orchestrator/src services/agent-orchestrator/tests
```

Tests use temporary directories and fake external services. SDK compilation does not establish live Codex authentication or model entitlement. Node's SQLite API may emit an experimental warning on Node 22.

## Live configuration

Live execution is optional and unverified in this delivery. Provide `LAB_MODE=live`, `LAB_INTERNAL_TOKEN`, `LAB_BROWSER_TOKEN`, `LAB_DATA_DIR`, `LAB_EXECUTION_CONFIG`, `LAB_PLANNER_MODEL` and the chosen planner provider's credentials. Codex uses its own approved local authentication. Never put service secrets in browser bundles. The live browser access field holds its bearer in page memory only.

`LAB_EXECUTION_CONFIG` points to a JSON object with `mode: "live"`, `project`, absolute `root`, registered `workspaces` mapping names to paths beneath root, and `checks` mapping IDs to `{argv: [executable, ...args], timeout_ms: 30000}`. Configure real checks; the `fixture` check is demo-only. Planner tasks must use the configured check identifiers. The default contract check name is `fixture`, so customize the planner/task contract for real repositories. Paths are resolved against the approved root, including symlink containment. Run one execution owner per state database/workspace root.

Start Python with `uv run --project services/agent-orchestrator uvicorn orchestrator.api:app --host 127.0.0.1 --port 8000`, then Node with `node services/control-plane/dist/main.js`. Internal token must match. `CODEX_BASE_URL` configures Python's execution URL; `LAB_ORCHESTRATOR_URL` configures the Node gateway URL. Keep both loopback-bound.

## Durability and safety boundaries

Graph checkpoints do not persist Codex thread internals. NestJS stores thread mappings separately and retains workspace leases when execution is uncertain. Do not clear a lease or replay an uncertain task until external execution has been reconciled. This version intentionally offers no automatic unsafe recovery shortcut.

Approvals bind the exact assignment revision. The UI can demonstrate denial and gating. Granting approval does not authorize a protected executor that has not been implemented: sensitive execution remains blocked at NestJS. Shell checks are registered server-side; request payloads cannot supply commands.

The implementation starts serially with one writer per workspace. Multiple independent registered workspaces can be admitted by Node, but graph worktree creation, branch integration and conflict resolution are not delivered. No protected merge/deployment operation is exposed.

SQLite is the implemented local checkpointer/store. To introduce PostgreSQL, replace the SqliteSaver construction in WorkflowService with `langgraph.checkpoint.postgres.PostgresSaver.from_conn_string`, call its schema setup, provide its lifetime management and concurrency tests. Installing the dependency alone does not enable a PostgreSQL backend.

## Tools and publication

Memory candidates need explicit review and passed source evidence before promotion. `ScopedTools` exposes memory, task, approval, document and search capabilities under a bound project/run. `MCPTools` uses the supported Streamable HTTP adapter and exact HTTPS endpoint/tool/schema allowlists. It is opt-in and not configured by demo startup.

`MarkdownPublisher` defines a lab adapter contract, not a claim of compatibility with an arbitrary document service: POST `/documents`, GET `/documents/receipt` for reconciliation, and GET `/documents` with a `q` parameter. Receipts require matching READY, document ID, project, idempotency key and content hash. Configure an adapter to the deployed service's actual schema before live use. Demo workflows create local memory candidates; they do not automatically publish externally or promote knowledge.

## Existing controller integration

The supplied spec assumes an existing SDK task boundary. The inspected sibling controller instead owns a Codex app-server subprocess. This lab remains isolated and does not replace or attach to those sessions. To integrate, mount the gateway/task boundary in the existing authenticated NestJS host, map its project registry and session IDs, and choose one execution transport owner. Reuse Angular request/timeline components after regression testing visual selection and existing sessions. This migration is outside the delivered directory.

Read the [end-to-end implementation guide](docs/deep-agent-harness-langgraph-end-to-end-guide.md) for installation, the request path, source references, logging and recovery.

See [reviewed plan](docs/implementation-plan.md), [contracts](docs/contracts.md), [architecture](ARCHITECTURE.md), and [design checklist](DESIGN.md). The original blueprint remains unchanged.

### Optional authenticated integration routes

Python exposes `/v1/runs/{run_id}/integrations/documents` (POST publish, GET search), `/documents/{key}/reconcile` (POST), and `/mcp` (POST), all requiring the internal bearer and existing project/run scope. These are coordinator service routes, not browser-exposed endpoints.

Set `LAB_DOCUMENT_URL` + `LAB_DOCUMENT_TOKEN` for the document adapter. Set `LAB_MCP_URL` + `LAB_MCP_TOKEN` + `LAB_MCP_TOOLS` (JSON agent-to-tool-name arrays) for a trusted MCP server. Enable only needed names in comma-separated `LAB_INTEGRATION_PERMISSIONS`: `publish_markdown`, `reconcile_markdown`, `search_documents`, `mcp_call`. Default is deny; construction performs no network calls. An authenticated operator must request publication explicitly. The service does not silently publish after a coding task.

Live execution state and artifacts must reside outside writable repositories. Artifact references are relative to the service data directory's `artifacts/` folder; workspace `.artifacts` paths are ignored.
