---
name: implement-development
description: Execute a reviewed development plan, verify its acceptance criteria, and record implementation evidence. Use for the implementation stage of planned repository work; do not activate for planning-only requests or require a plan for small direct changes.
---

# Implement development

Run this stage in the main conversation by default. Read the reviewed plan,
applicable instructions, relevant code and tests; apply matching language and
technology skills. Verify plan assumptions against current files and inspect
working-tree changes before editing. Preserve unrelated and concurrent work.
This skill does not authorize delegation.

In main-thread mode, set the task summary to In progress. Implement tasks in dependency order using
project conventions. Add meaningful tests when warranted by behavior changes,
and maintain affected documentation, manifests, and indexes under
$CODEX_HOME/workflows/development.md. Record minor deviations. For material scope
or approach changes, revisit planning and revise the plan before proceeding.

Run applicable checks within existing permissions. Inspect the final changes;
verify each acceptance criterion using tests, inspection, or observed behavior,
identifying the evidence type. For UI work, follow
$CODEX_HOME/workflows/ui-testing.md. Fix introduced failures and rerun affected
checks after final edits. Distinguish pre-existing/environmental failures; never
weaken valid tests or criteria to pass. Mark unavailable checks BLOCKED and stop
retries that yield no new progress with a concrete blocker.

Prepare a proportionate summary using $CODEX_HOME/references/task-records.md;
in main-thread mode, save it to the task record:

- Outcome/status, completed and remaining task IDs, changed files and behavior.
- Plan deviations and reasons, or None.
- Acceptance table: Criterion | PASS / FAIL / BLOCKED | Evidence | Remaining action.
- Test table: Check | Command or method | Working directory | Result | Evidence.
- Checks not run and why; whether evidence applies to final changes; local
  versus deployed verification; remaining issues and exact next steps.
- Verified reusable discoveries for authoritative documentation, when relevant.

Keep stage transitions, material findings, and verification outcomes visible in
the main conversation. Activity log files supplement these updates; they are
not a live transcript. Log meaningful milestones under AGENTS.md.

When explicitly delegated, edit only files assigned in the handoff and return
the summary to the main agent. Coordinate ownership changes through the main
agent; preserve other agents' edits. The main agent owns task records and shared
index updates unless one index is explicitly assigned to this builder. The main
agent reviews final changes and evidence before saving the summary. Do not
delegate further or modify shared agent definitions or generated native memory.

For browser UI testing/debugging, use $CODEX_HOME/tools/ui-testing-and-debugging/README.md and its requirements gate. Computer Use is the primary browser driver; inspect DevTools network payload/response and console as needed, and fix/retest until scoped stability or a concrete blocker. Keep shared UI testing/debugging Markdown and UI run records under that tool directory; workflows/ui-testing.md remains the entry point.
