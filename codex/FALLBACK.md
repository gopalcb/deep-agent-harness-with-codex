# Codex quota fallback

## AWS execution placeholder

Copy the nonsecret settings from `.env.example` into your process environment.
Replace `YOUR_AGENT_ID` and `YOUR_ALIAS_ID` with the existing Bedrock agent and
deployed alias, set its region, then enable `LAB_BEDROCK_ENABLED=true`.
Placeholders are rejected before invoking AWS. The application does not load
`.env` files automatically.

The adapter calls `boto3.client('bedrock-agent-runtime').invoke_agent(...)`
directly. Its parameters are `agentId`, `agentAliasId`, `sessionId`, and
`inputText`. The existing agent configuration chooses Qwen or another supported
model; no model ID is passed by this adapter. Use an existing AWS profile or role
with `bedrock:InvokeAgent` permission for the chosen agent alias.

The response stream is collected into text and closed. Empty responses, stream
errors and unsupported action-group return-control are not accepted as success.
There is no fabricated AWS execution in demo mode: demo returns the Codex fixture
and never reaches fallback.

## Why this adapter exists

Codex remains the normal coding agent. The alternate AWS agent is an explicit
continuity option when the Codex usage allowance is exhausted. It is not selected
because tests fail, a model response is unsatisfactory, or authentication expires.
The agent/model configured in AWS determines model choice and cost; the local
adapter cannot establish that Qwen is configured or that a request is cheaper.

## Request sequence

1. The caller submits a prompt to `/api/prompt`. Live calls require the configured
   browser bearer. The adapter currently runs independently of portal authentication.
2. The adapter sends the unchanged prompt to `codex exec` using stdin. Codex owns
   analysis, planning, file edits and its ordinary validation behavior.
3. The process exits before the adapter inspects its JSON events. This prevents the
   fallback from overlapping that Codex process; it does not lock other requests.
4. An error code `usage_limit_reached` or `insufficient_quota`, or the explicit
   usage-limit message, raises `CodexQuotaExhausted`. Other failures remain errors.
5. If fallback is enabled, configuration is validated and a private handoff record
   is written before the remote call. The record's UUID is also the AWS session ID.
6. The configured Bedrock agent receives the request and checkpoint. Its existing
   instructions and tools must provide planning, implementation and workspace access.
7. Trusted local validation commands run after the remote response. The final
   checkpoint records their exit codes and the validation status.

## Ownership and limitations

`api.py` owns request validation, authentication and Codex process handling.
`fallback.py` owns quota recognition, remote invocation, checkpoint records and
local acceptance checks. There is no second local coding loop or automatic repair.
The standalone `deep-agents/` classifier is retained but not called by this path.
Calling an existing Bedrock agent is not the same as running a local Deep Agents
LangGraph executor; that integration has not been implemented.

The current endpoint gives Codex workspace-write sandbox access and lets Codex
interpret whether a prompt actually asks for edits. Do not treat this endpoint as
a read-only question API. There is no per-workspace concurrency lock, cancellation,
automatic checkpoint resume, or independent proof that remote work changed the
intended files. Use one request at a time against an isolated lab workspace.

## Failure interpretation

| Result | Meaning | Next action |
| --- | --- | --- |
| Codex response | Normal Codex execution returned | Inspect its reported outcome |
| `validated` | Every configured local command exited zero | Review requirement coverage and actual changes |
| `needs_validation` | No checks configured, or a check failed | Inspect and validate before accepting work |
| `uncertain` checkpoint | Remote call or subsequent validation was interrupted | Inspect AWS session and workspace before another invocation |
| HTTP 502 | Execution could not return normally | Inspect the private checkpoint if one was created |

No automatic retry occurs after an uncertain remote call. Checkpoint files contain
the prompt and model response, so treat them as private project data. They do not
contain an automatically extracted Codex plan or full conversation history.

The prompt endpoint tries Codex first. Only an explicit usage-limit error activates
the opt-in existing Bedrock agent. Authentication, rate-limit, network and ordinary
execution failures do not activate fallback. Demo mode never invokes AWS.

Configure `LAB_BEDROCK_ENABLED=true`, `LAB_BEDROCK_REGION`,
`LAB_BEDROCK_AGENT_ID`, `LAB_BEDROCK_ALIAS_ID`, `LAB_WORKSPACE`, and
`LAB_CHECKPOINT_DIR` outside the workspace. AWS credentials use the normal SDK
credential chain. Do not place them in request payloads.

The configured remote agent must already have authorized tools for the target
workspace and its planning/implementation workflow. InvokeAgent alone cannot edit
local files. No repository contents are automatically uploaded. Local checkpoints
store the request, remote session, response and validation exit codes with private
file permissions. They are records, not automatic cross-session model memory.

`LAB_VALIDATION_COMMANDS` contains trusted server-configured argv arrays. No shell
is used. With no checks or failed checks, the response is `needs_validation`.
Passed checks produce `validated`, which does not establish requirement coverage.
Ambiguous remote errors produce `uncertain`; there is no automatic write retry.

Remaining integration work: actual remote workspace tools, plan/change/checkpoint
transfer from an interrupted Codex thread, bounded repair, explicit resume API,
LangGraph execution and reviewed persistent memory. The existing Deep Agent router
is bypassed on the normal Codex-first request path.

Verified locally: six quota-gate cases and Python compilation. AWS invocation and
end-to-end fallback implementation remain unverified; no live AWS call was made.
