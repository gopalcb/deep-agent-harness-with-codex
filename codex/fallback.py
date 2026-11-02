"""Connect Codex quota failures to a configured alternate execution provider.

Entry point and caller:
    codex/api.py calls run_fallback(prompt, workspace) only after catching
    CodexQuotaExhausted. This module is imported; it is not a separate HTTP server
    or command-line program. is_quota_error() is used while parsing Codex events.

How execution works:
    run_fallback() checks the opt-in switch and provider settings, reads trusted
    validation commands, and creates a private checkpoint outside the workspace.
    It calls deep-agents/workflow.py's run_workflow() with either invoke_bedrock()
    or invoke_local(). The graph calls that adapter separately for planning and
    implementation; its save callback records stage progress in the checkpoint.

Pseudocode:
    reject disabled or incomplete configuration
    choose existing Bedrock agent or local model adapter
    create task ID and private checkpoint
    run plan -> implement -> validate graph with the chosen adapter
    save results; on exception record uncertain and propagate the error

AWS adapter:
    invoke_bedrock() calls boto3 bedrock-agent-runtime InvokeAgent with the existing
    agent ID, alias and task session. AWS configuration determines the actual model.
    It sends the current stage and collects response chunks without automatic SDK
    retries. The workflow applies allowed file proposals locally; configure the
    remote agent to return proposals rather than independently edit the same files.

Checkpoints are task records, not automatic crash recovery or cross-task memory.
Source content and check output selected by the graph are shared with the provider.
"""

import json
import os
import sys
import uuid
from pathlib import Path

import boto3
from botocore.config import Config

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'deep-agents'))
from workflow import invoke_local, run_workflow


class CodexQuotaExhausted(RuntimeError):
    """Identify the sole failure allowed to activate the alternate runtime."""


# Restrict provider switching to explicit usage-quota signals in error envelopes.
# Authentication expiry, ordinary throttling and tool failures remain Codex errors.
def is_quota_error(event: dict) -> bool:
    """Accept explicit quota signals from error events, never ordinary output."""
    if event.get('type') not in {'error', 'turn.failed'}:
        return False

    error = event.get('error', event)
    if not isinstance(error, dict):
        return False

    return error.get('code') in {'usage_limit_reached', 'insufficient_quota'} or (
        "you've hit your usage limit" in str(error.get('message', '')).lower()
    )


# Send the current workflow stage to the existing AWS agent using its deployed alias.
# Reuse the task session across stages and disable SDK retries because remote actions
# may already have happened when a connection fails. Close the response stream always.
def invoke_bedrock(state: dict, client=None) -> str:
    """Invoke once with a stable session; never retry ambiguous remote writes."""
    runtime = client or boto3.client(
        'bedrock-agent-runtime',
        region_name=os.environ['LAB_BEDROCK_REGION'],
        config=Config(retries={'total_max_attempts': 1}, read_timeout=300),
    )

    response = runtime.invoke_agent(
        agentId=os.environ['LAB_BEDROCK_AGENT_ID'],
        agentAliasId=os.environ['LAB_BEDROCK_ALIAS_ID'],
        sessionId=state['id'],
        inputText=json.dumps(
            {
                'instruction': state.get('instruction', 'Follow the current workflow stage.'),
                'checkpoint': state,
            }
        ),
        enableTrace=False,
    )

    output = ''
    stream = response['completion']

    try:
        for event in stream:
            if 'chunk' in event:
                output += event['chunk']['bytes'].decode()
            elif 'trace' not in event:
                # Return-control requires a local tool bridge; never silently accept it.
                raise RuntimeError('Bedrock returned an error or requires tool return-control')

    finally:
        stream.close()

    if not output.strip():
        raise RuntimeError('Bedrock returned no agent response')

    return output


# Validate operator settings before sharing source or invoking a billable provider.
# Create a private task record, select one adapter, and run the application-owned graph.
# An exception leaves an uncertain checkpoint for inspection rather than a blind retry.
def run_fallback(prompt: str, workspace: str) -> dict:
    """Persist a handoff and accept completion only after configured local checks."""
    if os.environ.get('LAB_BEDROCK_ENABLED') != 'true':
        raise RuntimeError('Codex quota exhausted; Bedrock fallback is not enabled')

    # Validate configuration before making a billable remote request.
    provider = os.environ.get('LAB_FALLBACK_PROVIDER', 'bedrock')
    if provider not in {'bedrock', 'local'}:
        raise ValueError('Fallback provider must be bedrock or local')

    required = (
        ('LAB_BEDROCK_REGION', 'LAB_BEDROCK_AGENT_ID', 'LAB_BEDROCK_ALIAS_ID')
        if provider == 'bedrock'
        else ('LAB_LOCAL_MODEL',)
    )

    for name in required:
        value = os.environ.get(name, '')
        if not value or value.startswith('YOUR_'):
            raise ValueError(f'{name} must identify your configured AWS agent')

    checks = json.loads(os.environ.get('LAB_VALIDATION_COMMANDS', '[]'))

    if not isinstance(checks, list) or any(
        not isinstance(command, list)
        or not command
        or any(not isinstance(arg, str) or not arg for arg in command)
        for command in checks
    ):
        raise ValueError('Validation commands must be lists of nonempty argv strings')

    root = Path(workspace).resolve(strict=True)
    directory = Path(os.environ['LAB_CHECKPOINT_DIR']).resolve()
    if directory == root or root in directory.parents:
        raise ValueError('Checkpoint directory must be outside the workspace')

    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    state = {
        'id': str(uuid.uuid4()),
        'prompt': prompt,
        'workspace': str(root),
        'status': 'handoff',
        'checks': [],
        'note': 'Inspect workspace through authorized configured tools; no repository contents are automatically uploaded.',
    }

    path = directory / f'{state["id"]}.json'
    with path.open('x', encoding='utf-8') as stream:
        os.chmod(path, 0o600)
        json.dump(state, stream)

    try:

        # Save stage progress in the same private task file; this is task memory.
        # Recording a checkpoint does not automatically resume an interrupted request.
        def save(current: dict) -> None:
            """Persist each completed workflow stage for inspection."""
            path.write_text(json.dumps(current), encoding='utf-8')

        run_workflow(
            state, root, checks, invoke_bedrock if provider == 'bedrock' else invoke_local, save
        )

    except Exception:
        # The remote agent may have acted even if its response was interrupted.
        state['status'] = 'uncertain'
        raise

    finally:
        path.write_text(json.dumps(state), encoding='utf-8')

    return {**state, 'provider': provider, 'checkpoint': str(path), 'thread_id': None}
