"""Main HTTP entry point for the Codex-first harness.

How it is started:
    ../.venv/bin/python -m uvicorn api:app --app-dir codex --port 3100
    Uvicorn imports this file and serves the module-level FastAPI object `app`.
    There is no main() function. POST /api/prompt calls execute(); health() and
    config() serve the two small informational endpoints.

Who calls what:
    An HTTP client supplies a prompt and, in live mode, the browser bearer token.
    execute() validates access and calls run_codex(). run_codex() passes the exact
    prompt through stdin to the Codex CLI and parses its JSON events after exit.
    Only CodexQuotaExhausted calls fallback.run_fallback(). Ordinary failures are
    reported as HTTP errors. The optional classifier service is not called here.

Pseudocode:
    receive and validate prompt
    authenticate request
    try Codex in the configured workspace
    if a confirmed quota error occurred:
        run the configured fallback graph
    otherwise return the Codex response or report the execution error

Execution boundary:
    The subprocess finishes before fallback begins, preventing overlap with that
    Codex process. This does not serialize other requests or other workspace users.
    Demo mode returns a fixture and never invokes either live executor. Optional
    static hosting is enabled only when LAB_UI_DIR explicitly names built assets.
"""

import json
import os
import subprocess
from pathlib import Path

from fallback import CodexQuotaExhausted, is_quota_error, run_fallback
from fastapi import FastAPI, HTTPException, Request
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, field_validator


class Prompt(BaseModel):
    """Validate a prompt without changing its contents."""

    model_config = ConfigDict(extra='forbid')
    prompt: str

    # Reject unusable input at the HTTP boundary while preserving the exact prompt.
    @field_validator('prompt')
    @classmethod
    def validate_prompt(cls, value: str) -> str:
        """Reject blank or oversized prompts."""
        if not value.strip() or len(value) > 32000:
            raise ValueError('prompt must contain 1 to 32000 characters')

        return value


# Run Codex synchronously so it has stopped before fallback can edit the workspace.
# Only structured quota errors activate the alternate executor; stdout text does not.
def run_codex(prompt: str, route: str) -> dict:
    """Pass one unchanged prompt through stdin to a normal Codex turn."""
    if os.environ.get('LAB_MODE', 'demo') == 'demo':
        return {
            'response': f'Demo only: Codex would receive this {route} prompt unchanged: {prompt}',
            'thread_id': None,
        }

    workspace = os.environ['LAB_WORKSPACE']
    sandbox = 'read-only' if route == 'question' else 'workspace-write'

    result = subprocess.run(
        ['codex', 'exec', '--json', '--sandbox', sandbox, '-C', workspace, '-'],
        input=prompt,
        capture_output=True,
        text=True,
        check=False,
    )

    # Inspect structured errors only; arbitrary command output cannot enable AWS.
    response, thread_id = '', None
    for line in result.stdout.splitlines():
        event = json.loads(line)
        if is_quota_error(event):
            raise CodexQuotaExhausted('Codex usage quota exhausted')

        if event.get('type') == 'thread.started':
            thread_id = event['thread_id']

        if (
            event.get('type') == 'item.completed'
            and event.get('item', {}).get('type') == 'agent_message'
        ):
            response = event['item']['text']

        if event.get('type') in {'turn.failed', 'error'}:
            raise RuntimeError('Codex turn failed')

    if result.returncode:
        raise RuntimeError('Codex execution failed')

    return {'response': response, 'thread_id': thread_id, 'provider': 'codex'}


app = FastAPI(title='Codex prompt adapter')


# Public liveness intentionally exposes no credentials or workspace information.
@app.get('/health')
def health() -> dict:
    """Return public liveness."""
    return {'status': 'ok'}


# Let clients distinguish demo responses from configured live execution.
@app.get('/api/config')
def config() -> dict:
    """Expose the execution mode without credentials."""
    return {'mode': os.environ.get('LAB_MODE', 'demo')}


# Authenticate the caller, try Codex first, and catch only the dedicated quota signal.
# Other failures become HTTP errors instead of silently switching execution providers.
@app.post('/api/prompt')
def execute(payload: Prompt, request: Request) -> dict:
    """Run the unchanged prompt through Codex, with one quota-only fallback."""
    mode = os.environ.get('LAB_MODE', 'demo')

    if mode == 'demo':
        origin = request.headers.get('origin')
        if origin and origin not in {
            f'http://127.0.0.1:{request.url.port}',
            f'http://localhost:{request.url.port}',
        }:
            raise HTTPException(403, 'Cross-origin request rejected')

    elif request.headers.get(
        'authorization'
    ) != f'Bearer {os.environ.get("LAB_BROWSER_TOKEN", "")}' or not os.environ.get(
        'LAB_BROWSER_TOKEN'
    ):
        raise HTTPException(401, 'Browser authorization required')

    try:
        route = 'implementation'
        try:
            return {'route': route, **run_codex(payload.prompt, route)}
        except CodexQuotaExhausted:
            return run_fallback(payload.prompt, os.environ['LAB_WORKSPACE'])

    except (
        subprocess.SubprocessError,
        ValueError,
        RuntimeError,
        KeyError,
    ) as error:
        raise HTTPException(502, 'Prompt execution unavailable') from error


# Static hosting is optional; the copied telemetry UI uses its existing API host.
# Configure an explicit built UI path only when serving it from this adapter.
if os.environ.get('LAB_UI_DIR'):
    ui = Path(os.environ['LAB_UI_DIR']).resolve(strict=True)
    app.mount('/', StaticFiles(directory=ui, html=True), name='ui')
