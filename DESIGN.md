---
file-group: workflow-docs
project: deep-agent-harness-with-codex-lab
title: Engineering lab DESIGN
---
# Lab design

Single-page engineering workbench for developers creating and inspecting a bounded workflow. There are no existing pages or shared components in this new project; no convention counts can be inferred. The specification supplies the required roles. Native form controls are canonical; Angular App owns shared loading/error/state behavior, styles.css owns tokens.

A pale blue instrument panel, navy text, cobalt actions and teal success, with amber approval states. Display: system rounded sans; body: system sans; identifiers: monospace. A dependency rail connects the task rows, making execution order the signature element. Avoid decorative metrics or invented activity. Two-column request/results layout collapses at 760px.

Tokens: background #eef3f9, surface #ffffff, ink #15283f, muted #52647a, accent #245bcc, success #176951. Spacing 4/8/12/16/24/32px; radius 12px. Visible focus uses accent outline. All status text remains readable without color. Reduced motion disables transitions. Theme values live in styles.css.

## Page checklist and behavior contract
- Header: h1 Lab control room; visible demo/live connection status.
- Request form: labeled template select, instruction textarea, optional URL/selector, sensitive-action checkbox; required instruction; submit disabled while pending.
- Failure: role=alert with actionable text; preserve draft and request key after ambiguous failures.
- Run status: aria-live=polite; cancellation only while active.
- Approval: explicit approve/deny, no dispatch before approved; action details and revision visible.
- Task list: role, ID, dependencies, checks, status, thread reference and artifacts; empty state explains next step.
- Timeline: agent filter; stable event IDs and reconnect cursor; no duplicate rows.
- Results: verified checks distinguished from simulated execution and unrun live services.
- Keyboard/native controls, no horizontal overflow on narrow screens, 44px controls.
- No secrets in browser storage or bundle; live bearer token held in memory only when supplied by operator.

Verification: Angular compiler, integration HTTP checks and browser checks when Computer Use is available. Build success alone does not prove browser behavior.
