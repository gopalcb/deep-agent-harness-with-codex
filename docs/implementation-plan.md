---
kind: plan
project: deep-agent-harness-with-codex-lab
assigned_to: codex
title: Implement the Codex-first LangGraph engineering lab
file-group: workflow-docs
---
# Reviewed implementation plan

Planning agent /root/plan (high_effort) read the specification and audited the sibling controller. Separate /root/plan_review (high_effort) reviewed it. Main waited for planning before starting review. User approved credential-free implementation on 2026-10-30. All new code stays in this directory; original specification and sibling projects remain untouched.

## Audit and decisions
Target initially contained only the specification. Sibling agent-runtime-controller/backend/codex.ts launches codex app-server; it does not expose the assumed SDK task API. Deliver a standalone mountable lab boundary and Angular companion. Existing-controller integration and private live service acceptance remain explicitly unverified. Revised section 12 takes precedence over the earlier Phase-0-only kickoff. NestJS owns Codex; Python uses HTTP only. Deep Agents gets artifact-only planning/research tools, never repository editing or shell. SQLite checkpointing is a local-mode choice; PostgreSQL checkpointer configuration is documented separately.

## Work items and acceptance
| ID | Owner | Work | Depends on | Acceptance |
|---|---|---|---|---|
| T1 | main | Scaffold, lock dependencies, shared models/contracts | review | strict schemas, reproducible install, scope preserved |
| T2 | persistence worker | SQLite records, idempotency, rotating JSONL, replay/redaction | T1 | restart/dedup/concurrency/redaction tests |
| T3 | graph worker | LangGraph direct/planned DAG, durable checkpoints, HTTP Codex client, bounded repair, approval/cancellation | T1,T2 contracts | dependency/recovery/denial/uncertainty tests using real graph |
| T4 | persistence worker | memory, restricted tools/MCP, Markdown publication receipts | T1,T2 | project isolation, evidence-gated promotion, authenticated fake-server tests, no uncertain retries |
| T5 | main | NestJS SDK adapter, authoritative leases, admission journal, registered checks | T1 | start/resume/cancel/replay/auth/idempotency tests; real SDK compile |
| T6 | graph worker + main | Python routes (worker), Angular companion and gateway (main) | T3,T5 | direct/planned vertical flows, approvals, timeline, errors, cancellation |
| T7 | main + separate validator | integration and adversarial checks | T2–T6 | evidence table, failures repaired, live limitations explicit |
| T8 | separate summary agent + main review | detailed summary and agent/context accounting | T7 | accurate checks/limits/agent sequence, no invented occupancy |

## Ownership and contracts
See contracts.md for exact models, signatures and endpoints. Graph worker owns workflow/planning/context/codex_client/workspaces/api/routing/config/validation and their tests. Persistence worker owns storage/events/memory/tools/documents and their tests. Main owns contracts, manifests/locks, Node/Angular, integration tests and shared documentation. No recursive delegation or competing file edits.

## Plan review corrections
1. Standalone acceptance is distinct from existing-controller integration.
2. NestJS atomically admits one writer per workspace and retains uncertain leases.
3. Freeze interfaces before parallel implementation.
4. Wire 70% policy into actual Deep Agents model calls; inspect tool inventory and artifact isolation.
5. Bind approvals to exact action revision before dispatch. Empty checks never establish verification.
6. Publication timeout remains uncertain until authenticated receipt reconciliation.
7. Report SQLite versus PostgreSQL capabilities accurately; separate-worktree parallelism needs conflict tests before claiming support.

## Verification
Python: uv sync --locked, ruff, pytest. Node: npm ci, build, node tests. Cross-service tests use disposable fixtures and explicit fake model/Codex transport. Validate restart, failed checks, bounded repair, approval denial, cancellation, replay, idempotency conflicts, cross-project scope, path escapes and memory expiry. Browser testing follows available Computer Use requirements and cleanup. No live model, private authentication, sibling migration, push or deployment is authorized by local completion.

## Context management
Implement 70% middleware for configured Python model capacity, reserving output/headroom; checkpoint/offload/summarize/recount and refuse oversized inputs. Codex occupancy is unknown; cumulative usage is telemetry only. Native agents expose neither percentage telemetry nor manual compaction controls, so use bounded fresh assignments and concise handoffs, report unknown status rather than fabricated compaction.
