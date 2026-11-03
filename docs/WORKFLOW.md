# Quota fallback workflow

`workflow.py` now enforces a LangGraph sequence: plan, implement, validate.
Failed configured checks return to implementation once, with their bounded output.
Two attempts is the fixed limit. Missing checks never produce validated status.

Choose `LAB_FALLBACK_PROVIDER=bedrock` for the existing boto3 agent adapter, or
`local` for a small model already served by Ollama at 127.0.0.1:11434. Set
`LAB_LOCAL_MODEL` to its installed model name. The local option is a Python HTTP
adapter to a locally hosted model, not a model trained or embedded by this project.
No model is downloaded automatically.

Both options require `LAB_BEDROCK_ENABLED=true` (the existing master fallback
switch), `LAB_WORKSPACE`, `LAB_CHECKPOINT_DIR`, `LAB_EDIT_FILES` as a JSON list of
relative editable filenames, and `LAB_VALIDATION_COMMANDS` as trusted argv arrays.
Bedrock additionally requires region, agent ID and alias settings.

Selected file contents and check output are shared with the selected model.
Choose only source files authorized for that destination; exclude secrets.
The implementation stage returns JSON file replacements, which Python restricts
to the selected files before writing. Model-generated shell commands are never run.
Use an isolated workspace and serialize requests; this is not a security sandbox.

Stage records preserve the plan, file context, changed files, attempts and check
results in the private checkpoint. This is task memory, not automatically promoted
cross-task knowledge. Automatic crash resume is not implemented.

This replaces the earlier prompt-only handoff described in codex/FALLBACK.md.
The AWS agent should return proposals instead of independently editing the same
workspace. Only confirmed Codex quota errors activate either adapter. Demo Codex
execution never activates fallback. Live AWS and local-model calls are unverified.
