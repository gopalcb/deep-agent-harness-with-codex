"""Application-owned LangGraph fallback: plan, implement and independently validate.

Entry point and caller:
    codex/fallback.py imports run_workflow() and supplies the task state, resolved
    workspace, trusted check commands, selected model adapter and checkpoint callback.
    This module has no HTTP endpoint or main() function. The optional classifier
    in routing.py is separate and is not needed to execute this graph.

How the graph works:
    plan() reads only LAB_EDIT_FILES and obtains a model plan. implement() asks the
    same adapter for JSON replacements, checks all target paths, then writes them.
    validate() runs operator-configured argv commands and records bounded output.
    next_step() sends a failed check back to implement() once. The graph stops after
    successful checks, absent checks, or two implementation attempts.

Pseudocode:
    resolve and validate editable paths
    plan = model(request, selected source files)
    repeat at most twice:
        proposals = model(plan, current files, previous validation failures)
        reject proposals outside editable paths
        apply replacement text
        results = run trusted local checks
        save task state
        if checks passed or no checks exist: stop
    return state with validated or needs_validation status

Provider adapters:
    invoke_bedrock() is supplied by fallback.py. invoke_local() below calls an
    already-running Ollama server using LAB_LOCAL_MODEL. Both return plain text;
    implementation responses must contain the documented JSON object, not Markdown.

The allowlist limits intended edits but is not an operating-system sandbox. Use an
isolated workspace and serialize requests. Stage checkpoints retain task context;
this graph does not implement automatic restart/resume or general knowledge memory.
"""

import json
import os
import subprocess
from pathlib import Path
from typing import TypedDict

import httpx
from langgraph.graph import END, START, StateGraph


class State(TypedDict, total=False):
    """Keep the plan, attempts and independent evidence explicit."""

    plan: str
    response: str
    attempts: int
    checks: list
    status: str
    changed_files: list


# Compile the same workflow for either model adapter. The model supplies proposals;
# this code owns file boundaries, validation commands and the two-attempt repair limit.
def run_workflow(state: dict, root: Path, commands: list, invoke, save) -> dict:
    """Execute two implementation attempts at most; checks alone gate completion."""
    root = root.resolve(strict=True)
    allowed = json.loads(os.environ.get('LAB_EDIT_FILES', '[]'))
    if not isinstance(allowed, list) or not allowed:
        raise ValueError('LAB_EDIT_FILES must explicitly list editable files')

    paths = {}
    for name in allowed:
        if not isinstance(name, str) or Path(name).is_absolute():
            raise ValueError('Editable paths must be relative strings')

        path = (root / name).resolve()
        if root not in path.parents or '.git' in Path(name).parts or path.is_symlink():
            raise ValueError('Editable path escapes workspace or targets Git internals')

        paths[name] = path

    # Read only the explicitly selected files and ask for a plan before any writes.
    # Persist the plan so later implementation stages receive the same task context.
    def plan(current: State) -> dict:
        """Ask the selected model to plan against only explicitly shared files."""
        files = {name: path.read_text() if path.exists() else '' for name, path in paths.items()}
        if sum(len(content) for content in files.values()) > 100000:
            raise ValueError('Selected files exceed handoff budget')

        answer = invoke(
            {
                **state,
                'stage': 'plan',
                'files': files,
                'instruction': 'Return a concise implementation plan. Do not edit files.',
            }
        )

        state.update(plan=answer, files=files, status='planned')
        save(state)

        return {'plan': answer, 'attempts': 0}

    # Require JSON replacements rather than executing model-generated shell commands.
    # Check every proposed path and content type before writing the first file.
    # A repair receives the previous check results and current file contents.
    def implement(current: State) -> dict:
        """Apply validated replacement proposals only to the configured file set."""
        answer = invoke(
            {
                **state,
                **current,
                'stage': 'implement',
                'instruction': 'Return ONLY JSON: {"files": {"relative/path": "complete replacement text"}, "summary": "text"}. Follow the plan. Repair failed checks if supplied. No shell commands.',
            }
        )

        proposal = json.loads(answer)
        replacements = proposal['files']

        if not isinstance(replacements, dict) or not set(replacements) <= set(paths):
            raise ValueError('Model proposed files outside the editable set')

        if any(not isinstance(content, str) for content in replacements.values()):
            raise ValueError('File replacements must contain text')

        # Validate every proposed target before the first write.
        for name in replacements:
            if (root / name).resolve() != paths[name]:
                raise ValueError('Workspace path changed during execution')

        for name, content in replacements.items():
            paths[name].parent.mkdir(parents=True, exist_ok=True)
            paths[name].write_text(content)

        state['files'].update(replacements)

        state.update(
            status='implemented',
            attempts=current['attempts'] + 1,
            changed_files=sorted(set(state.get('changed_files', [])) | set(replacements)),
            response=proposal.get('summary', ''),
        )

        save(state)
        return {key: state[key] for key in ('attempts', 'changed_files', 'response')}

    # Run operator-configured argv commands independently of the model's success claim.
    # Keep bounded output for repair feedback; zero configured checks cannot validate work.
    def validate(current: State) -> dict:
        """Run trusted commands and feed bounded failure details into repair."""
        checks = []
        for command in commands:
            result = subprocess.run(command, cwd=root, capture_output=True, text=True, timeout=120)
            checks.append(
                {
                    'argv': command,
                    'exit_code': result.returncode,
                    'details': (result.stdout + result.stderr)[-4000:],
                }
            )

        status = (
            'validated'
            if checks and all(item['exit_code'] == 0 for item in checks)
            else 'needs_validation'
        )

        state.update(checks=checks, status=status)
        save(state)

        return {'checks': checks, 'status': status}

    # Retry only after an actual failed check and only while an attempt remains.
    # Stop on success, missing checks or the attempt limit to prevent endless repairs.
    def next_step(current: State) -> str:
        """Repair only real failed checks, within the fixed attempt limit."""
        return (
            'implement'
            if current['checks'] and current['status'] != 'validated' and current['attempts'] < 2
            else END
        )

    graph = StateGraph(State)

    graph.add_node('plan', plan)
    graph.add_node('implement', implement)
    graph.add_node('validate', validate)
    graph.add_edge(START, 'plan')
    graph.add_edge('plan', 'implement')
    graph.add_edge('implement', 'validate')
    graph.add_conditional_edges('validate', next_step)
    graph.compile().invoke({})

    return state


# Use an already-running local Ollama model through a small Python HTTP adapter.
# This does not download a model or start a server; the operator supplies its name.
def invoke_local(state: dict) -> str:
    """Call a locally hosted small model through Ollama's HTTP API."""
    response = httpx.post(
        'http://127.0.0.1:11434/api/generate',
        json={'model': os.environ['LAB_LOCAL_MODEL'], 'prompt': json.dumps(state), 'stream': False},
        timeout=300,
    )

    response.raise_for_status()

    return response.json()['response']
