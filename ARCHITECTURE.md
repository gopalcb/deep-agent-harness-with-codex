# Harness architecture

The local prompt API runs Codex first. A dedicated quota exception activates the
configured alternate provider only after the Codex subprocess exits.

The fallback validates operator settings, saves a private task checkpoint, and
executes LangGraph nodes: plan -> implement -> validate. Failed configured checks
allow one repair attempt. Model proposals can replace only selected files.
Missing checks never mark work validated. The model does not choose shell commands.

Bedrock uses boto3 InvokeAgent with the existing agent ID and deployed alias.
The local adapter uses Ollama HTTP. Both feed the same graph and task records.
Only selected source and bounded check output are shared with the model.

The standalone Deep Agent classifier is optional and bypassed by this path.
There is no portal, document-sharing API, deployment stack or watcher in this lab.
Use an isolated workspace and one active request; automatic resume, cross-task
memory and concurrent workspace ownership are not implemented.
