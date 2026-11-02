---
name: plan-development
description: Plan complex or consequential repository changes, or fulfill explicit implementation-planning requests. Use for the planning stage of the GB Systems development workflow; ordinary questions and small direct changes do not require it.
---

# Plan development

Run this stage in the main conversation by default. Load applicable language
and technology skills for the affected parts. Resolve supporting workflow and
task-record paths from CODEX_HOME. This skill does not authorize delegation.

Inspect applicable instructions, relevant code, tests, documentation, and related
task records. Verify assumptions against current files. Identify existing
approaches, reusable components, dependencies, and constraints.

Prefer established approaches when sufficient. Research unresolved gaps,
unstable external facts, or explicit research requests. Prefer primary sources;
record URLs, research date, recommendation reasons, and unresolved uncertainty.

Produce a proportionate Markdown plan with:

- Task title, summary, scope, and exclusions.
- Analysis, proposed approach, reusable components, and meaningful tradeoffs.
- Ordered tasks T-1, T-2, etc., with existing/proposed files, concrete changes,
  dependencies, acceptance criteria, and validation steps.
- Observable expected results and verifiable criteria AC-1, AC-2, etc.
- Verification mapped to criteria: commands, execution directories,
  prerequisites, expected outcomes, relevant edge cases and regressions.
  Separate local checks from integration/deployment checks. Include browser
  scenarios and viewports for UI work.
- Assumptions, risks, blockers, and intentional verification deferrals.

Review requirement coverage and actionability. Do not invent commands or project
capabilities. Keep implementation files unchanged during planning. The main
agent saves the reviewed plan and Planned summary using
$CODEX_HOME/references/task-records.md and logs the milestone. Planning-only
requests stop here; otherwise continue to the implementation stage.

When explicitly delegated, return the plan and milestones to the main agent
without writing any files or logs. Do not delegate further.

For browser UI testing/debugging, use $CODEX_HOME/tools/ui-testing-and-debugging/README.md and its requirements gate. Computer Use is the primary browser driver; inspect DevTools network payload/response and console as needed, and fix/retest until scoped stability or a concrete blocker. Keep shared UI testing/debugging Markdown and UI run records under that tool directory; workflows/ui-testing.md remains the entry point.
