---
name: python-development
description: Create, review, debug or refactor Python code using the project conventions for validation, simple functions, architecture documentation and code maps.
---

# Python Coder Skill

## Purpose

Use this skill whenever a Codex agent creates, reviews, refactors, or extends Python code.

The goal is to produce Python that is easy to read, compact without becoming dense, explicit about structure, and easy for another engineer or agent to modify later. Prefer simple, direct code over clever abstractions.

---

## 1. Core Principles

### Readability first

Code should make the execution flow obvious. Prefer a small number of meaningful functions over many wrappers.

Good:

```python
payload = validate_request(request)
result = process_request(payload)
save_result(result)
```

Avoid chains of tiny helpers that only move values around.

### Avoid too many small functions

Do not create small functions unless they represent a meaningful reusable operation or domain concept.

Bad:

```python
def get_name(payload: dict) -> str:
    return payload["name"]

def normalize_name(name: str) -> str:
    return name.strip()

def build_name(payload: dict) -> str:
    return normalize_name(get_name(payload))
```

A function should normally contain enough logic to justify its existence.

### Avoid oversized functions

Do not create large functions that mix unrelated concerns. Split a function when it:

- handles multiple meaningful responsibilities,
- becomes difficult to scan,
- contains deeply nested conditions,
- has a meaningful reusable section,
- would benefit from independent testing.

Do not split code merely to reduce line count.

### Keep function count intuitive

A reader should understand a file by scanning its function names.

Prefer:

```text
browser.py
- open_browser()
- submit_prompt()
- close_browser()
```

over a file containing many tiny implementation helpers such as `build_options()`, `set_profile()`, `click_editor()`, `insert_text()`, and similar functions unless they are independently necessary.

---

## 2. File-Level Documentation

Every Python file must start with a short module docstring describing:

1. the file's purpose,
2. its main responsibility,
3. how it connects to nearby modules when useful.

Example:

```python
"""
Handles browser startup and prompt submission for interactive web search.

This module owns Selenium browser interaction. Validation belongs in
validation.py and response extraction belongs in extractor.py.
"""
```

Whenever functions are added, removed, renamed, or their responsibilities change, review the module description and update it when needed.

Never leave stale module descriptions.

---

## 3. Function Documentation

Every project function must begin with a concise docstring.

Example:

```python
def submit_prompt(driver: WebDriver, prompt: str) -> None:
    """Enter the prompt in the active page and submit it."""
```

For simple functions, keep the docstring short and explain its purpose. For more complex functions, briefly describe important behavior and meaningful return values. Explain non-obvious logic in plain-language comments; include a small input/output example when it makes the behavior easier to understand.

Do not write long docstrings that merely repeat the implementation.

---

## 4. Function Naming

Use clear action-oriented names.

Prefer:

```text
validate_search_payload()
load_search_config()
open_browser()
```

### Never start project function names with `_`

Do not use:

```python
def _load_config() -> dict:
```

Use:

```python
def load_config() -> dict:
```

Python special methods such as `__init__` are exempt.

---

## 5. Parameters and Type Annotations

Avoid functions with too many parameters.

Bad:

```python
def create_agent(name, model, timeout, profile, tools, memory, skills, retries):
    ...
```

Prefer passing a validated config or payload when values naturally belong together:

```python
def create_agent(config: dict) -> dict:
    """Create an agent from validated configuration."""
```

Do not introduce a class or dataclass only to avoid a few parameters unless it makes the domain clearer.

### Do not use `*` for keyword-only argument separation

Avoid:

```python
def run_agent(prompt: str, *, timeout: int = 60) -> str:
```

Prefer:

```python
def run_agent(prompt: str, timeout: int = 60) -> str:
```

### Use simple type annotations

Use parameter and return types on project functions.

```python
def load_config(path: str) -> dict:
    """Load YAML configuration from disk."""
```

Prefer straightforward types:

```text
str
int
bool
dict
list
None
```

If a type becomes deeply nested, simplify it.

Prefer:

```python
def process_payload(payload: dict) -> dict:
```

over a difficult-to-read nested type such as:

```python
dict[str, list[dict[str, tuple[str, int | None]]]]
```

Always include a return type where practical:

```python
-> str
-> bool
-> dict
-> list
-> None
```

---

## 6. Imports

All imports must be at the top of the file.

Never import a library inside a function.

Bad:

```python
def load_yaml(path: str) -> dict:
    import yaml
```

Good:

```python
import yaml

def load_yaml(path: str) -> dict:
    """Load YAML data from the provided path."""
```

Use this grouping:

```python
# standard library
import json
from pathlib import Path

# third-party
import yaml
from selenium import webdriver

# project
from services.validation import validate_payload
```

Remove unused imports.

Never use wildcard imports:

```python
from module import *
```

---

## 7. Validation

Do not scatter payload, parameter, or configuration validation through business logic.

For Python projects that require validation, maintain a dedicated validation module:

```text
validation.py
```

or, if consistent with the project:

```text
services/validation.py
```

Validation belongs there for:

- required fields,
- basic type checks,
- allowed values,
- request payload shape,
- configuration shape,
- parameter checks,

Example:

```python
def validate_search_payload(payload: dict) -> dict:
    """Validate and normalize incoming interactive-search parameters."""
    prompt = payload.get("prompt")

    if not isinstance(prompt, str) or not prompt.strip():
        raise ValueError("prompt must be a non-empty string")

    return {
        **payload,
        "prompt": prompt.strip(),
    }
```

After validation, downstream workflow functions should assume the payload is valid instead of revalidating it repeatedly.

---

## 8. Error Handling

Catch exceptions only when the code can:

- recover,
- add meaningful context,
- translate the error into a domain-specific exception,
- guarantee cleanup.

Never silently swallow errors.

Avoid:

```python
try:
    ...
except Exception:
    pass
```

Prefer:

```python
try:
    config = load_config(config_path)
except OSError as error:
    raise RuntimeError(f"Unable to load config: {config_path}") from error
```

Use `finally` when resource cleanup must always happen.

---

## 9. Comments

Prefer good names over comments.

Avoid comments that restate obvious code:

```python
# get prompt
prompt = payload["prompt"]
```

Use comments for behavior that is not immediately obvious:

```python
# ChatGPT may keep the fallback textarea hidden while using a visible editor.
editor = find_active_prompt_editor(driver)
```

Remove commented-out code unless there is a clear temporary reason to keep it.

---

## 10. Classes vs Functions

Do not create classes automatically.

Prefer module-level functions when:

- little or no state is shared,
- the workflow is simple,
- functions naturally express the operations.

Use classes when:

- several operations share meaningful state,
- lifecycle management matters,
- interchangeable implementations are required,
- the class represents a real domain concept.

Do not create classes only for namespacing.

---

## 11. Reuse Without Over-Abstraction

Before adding a new function or file:

1. inspect the existing owner of that responsibility,
2. determine whether an existing function can be extended cleanly,
3. reuse existing logic when it reduces real duplication,
4. avoid a generic helper for a tiny single-use operation.

A reusable function should represent a meaningful operation, not simply relocate a few lines.

---

## 12. File Organization

Prefer fewer, well-focused files. Use blank lines between meaningful steps and wrap long expressions so code is easy to scan; do not compress code merely to save lines. Split oversized modules by responsibility without adding unnecessary wrappers.

For service-oriented APIs, keep HTTP route declarations in `routing.py`, domain operations in `services/agent_service.py` and similarly named service files, and configuration in `config.py` or YAML when needed. Keep these boundaries simple and reuse shared logic instead of duplicating it.

Create a new Python file only when it owns a distinct responsibility.

Good example:

```text
interactive-web-search/
├── cli.py
├── api.py
├── search-config.yaml
├── ARCHITECTURE.md
├── code-map.yaml
└── services/
    ├── browser.py
    ├── extractor.py
    └── validation.py
```

Avoid unnecessary folders and generic dumping grounds such as:

```text
utils/
helpers/
common/
shared/
misc/
```

unless the project has enough real shared logic to justify them.

Keep code near the domain that owns it.

---

## 13. ARCHITECTURE.md — Required for Every Python Project

Every Python project must maintain:

```text
ARCHITECTURE.md
```

Keep it brief but sufficient for an agent to understand the project before editing code.

Recommended sections:

```markdown
# Architecture

## Purpose
## Project Structure
## Main Execution Flow
## Module Responsibilities
## Configuration
## Data Flow
## Extension Points
```

The project structure should explain meaningful files and directories.

Example:

```text
cli.py
CLI entry point. Builds the request and starts the workflow.

services/browser.py
Owns Selenium browser startup and prompt submission.

services/extractor.py
Waits for and persists generated responses.

services/validation.py
Validates incoming payloads before workflow execution.
```

### Keep ARCHITECTURE.md synchronized

Review and update it whenever changes affect:

- project structure,
- execution flow,
- module responsibility,
- entry points,
- configuration,
- module relationships,
- major capabilities.

Do not make unnecessary architecture edits for minor internal implementation changes.

---

## 14. code-map.yaml — Required for Every Python Project

Every Python project must maintain:

```text
code-map.yaml
```

This is the exact lightweight blueprint of Python files and functions.

Recommended format:

```yaml
project: interactive-web-search

files:
  cli.py:
    purpose: CLI entry point for interactive search.
    functions:
      main:
        summary: Validate the request and execute the configured workflow.

  api.py:
    purpose: Reserved HTTP API entry point.
    functions: {}

  services/browser.py:
    purpose: Manage Selenium browser startup and prompt submission.
    functions:
      open_browser:
        summary: Open Chrome using the configured local profile.
      submit_prompt:
        summary: Enter and submit a prompt.
      close_browser:
        summary: Close the Selenium browser session.

  services/extractor.py:
    purpose: Extract and persist assistant responses.
    functions:
      wait_for_response:
        summary: Wait until the newest assistant response becomes stable.
      extract_response:
        summary: Extract generated assistant text.
      save_response:
        summary: Save response text to Markdown.

  services/validation.py:
    purpose: Validate workflow input.
    functions:
      validate_search_payload:
        summary: Validate and normalize search parameters.
```

### code-map.yaml synchronization rules

Update `code-map.yaml` in the same change whenever an agent:

- adds a Python file,
- removes a Python file,
- renames a Python file,
- adds a function,
- removes a function,
- renames a function,
- materially changes a function's responsibility.

Function names must exactly match the implementation.

Keep summaries brief.

Do not list imported third-party functions.

Do not turn the map into full documentation.

---

## 15. ARCHITECTURE.md vs code-map.yaml

Use them for different levels of understanding.

### ARCHITECTURE.md answers

- What is the project?
- How does it work?
- What is the main flow?
- Why do the modules exist?
- How do components connect?

### code-map.yaml answers

- Which Python files exist?
- Which functions are defined in each file?
- What does each function do?

`ARCHITECTURE.md` is conceptual.

`code-map.yaml` is structural.

---

## 16. Entry Points

Keep entry points thin but understandable.

Example:

```python
def main() -> None:
    """Run the interactive-search CLI."""
    config = load_config("search-config.yaml")
    payload = validate_search_payload(build_test_payload())
    run_search(config, payload)
```

An entry point should coordinate the workflow without containing detailed browser, persistence, parsing, or validation logic.

Do not break simple orchestration into many tiny wrappers.

---

## 17. Dependency Direction

Prefer a simple dependency flow:

```text
entry point
    ↓
validation/configuration
    ↓
workflow/domain service
    ↓
external integration
```

Avoid circular imports.

Lower-level modules must not import CLI or API entry points.

---

## 18. Side Effects

Make side effects obvious through names.

Examples:

```text
save_response()
open_browser()
send_request()
write_log()
```

Avoid hiding important side effects behind vague helper names.

For resources such as browser drivers, files, subprocesses, sockets, and temporary directories, guarantee cleanup.

Example:

```python
driver = open_browser(config)

try:
    ...
finally:
    close_browser(driver)
```

---

## 19. Avoid Premature Frameworks

Do not introduce these unless a real current requirement exists:

- dependency injection frameworks,
- repository patterns,
- abstract base classes,
- factories,
- event buses,
- plugin registries,
- service locators.

Build the simplest architecture that cleanly supports current requirements and obvious near-term extensions.

---

## 20. Constants

Use module-level constants when stable values improve readability:

```python
DEFAULT_TIMEOUT = 60
ASSISTANT_SELECTOR = '[data-message-author-role="assistant"]'
```

Do not create a dedicated constants file for a few values that naturally belong to one module.

---

## 21. Logging

Use logging when operational visibility is useful.

Prefer:

```python
import logging

logger = logging.getLogger(__name__)
```

Log meaningful events such as:

- workflow started,
- browser opened,
- prompt submitted,
- response extracted,
- output saved,
- recoverable failure.

Avoid logging every variable or every function call.

IMPORTANT: Do not mix logging for- python program / application within the monorepo vs. Agent interaction logging. They serve two different purposes. The python project (in a monorepo) logging is mainly to identify any issues or tracing the python program execution steps and these logs will live in that specific python project folder scope, not in the Agent interaction logging space. If the project needs to save logs, always create a logs folder in the local project root, for example, /agent-tools/interactive-web-search/logs.

For very small CLI tools, clear CLI output may be enough.

---

## 22. Testing

Tests should validate meaningful behavior rather than mirror implementation details.

Prioritize:

- validation rules,
- important transformations,
- workflow decisions,
- error behavior,
- external integration boundaries.

Avoid writing tests for trivial wrappers that probably should not exist.

Keep test organization proportional to project size.

---

## 23. Refactoring Rules

When refactoring Python:

1. preserve behavior unless behavior change is requested,
2. eliminate duplicate logic,
3. merge unnecessary tiny functions,
4. split only genuinely oversized or mixed-responsibility functions,
5. keep function names aligned with the workflow,
6. remove dead code and unused imports,
7. update module-level descriptions,
8. update affected function docstrings,
9. update `code-map.yaml`,
10. update `ARCHITECTURE.md` when structure or flow changed,
11. run available syntax, tests, or lint checks.

Do not refactor merely to introduce patterns or abstraction layers.

---

## 24. Adding New Functionality

Before implementation:

1. read `ARCHITECTURE.md`,
2. read `code-map.yaml`,
3. inspect the relevant existing modules,
4. identify which file currently owns the responsibility,
5. decide whether an existing function should be extended,
6. create a new function only when it represents a meaningful operation,
7. create a new file only when there is a distinct responsibility.

After implementation:

1. review function size and count,
2. review naming, imports, typing, validation, and docstrings,
3. update `code-map.yaml`,
4. update `ARCHITECTURE.md` if needed,
5. run verification.

---

## 25. Removing Functionality

When removing functionality:

- remove unused code,
- remove obsolete imports,
- remove related dead configuration,
- remove functions/files from `code-map.yaml`,
- update module descriptions,
- update `ARCHITECTURE.md` when architecture or flow changes.

Do not leave placeholder functions unless a near-term interface explicitly requires them.

---

## 26. Python Simplicity Practices

Prefer early returns when they reduce nesting:

```python
if not enabled:
    return None

result = run_task()
return result
```

Prefer built-in language features before adding dependencies.

Prefer `pathlib.Path` for filesystem paths.

After validation guarantees a required key, use direct dictionary access:

```python
prompt = payload["prompt"]
```

Use `.get()` when absence is valid:

```python
timeout = payload.get("timeout", 60)
```

Avoid overly clever comprehensions when a normal loop is easier to understand.

Use descriptive local variable names.

Keep mutation localized and obvious.

---

## 27. Things to Avoid

Avoid by default:

- unnecessary one-to-three-line helpers,
- huge multi-purpose functions,
- unclear function names,
- functions starting with `_`,
- excessive function parameters,
- `*` keyword-only separators,
- deeply nested type annotations,
- function-local imports,
- wildcard imports,
- validation inside business logic,
- stale docstrings,
- stale `ARCHITECTURE.md`,
- stale `code-map.yaml`,
- unnecessary classes,
- unnecessary files,
- generic `utils.py` dumping grounds,
- duplicate logic,
- premature design patterns,
- broad exception swallowing,
- hidden side effects,
- circular imports.

---

## 28. Review Heuristic

Before finishing a Python change, ask:

### Readability
Can another engineer understand the file's purpose and workflow quickly?

### Function boundaries
Does every function represent a meaningful operation?

### Function size
Is any function so small that it adds indirection without value?
Is any function so large that it mixes responsibilities?

### Naming
Can the workflow be understood by scanning function names?

### Validation
Are request, payload, config, and parameter checks centralized?

### Imports
Are all imports at the top?

### Typing
Do function parameters and returns have readable types?

### Documentation
Does every function have a concise docstring?
Does the module docstring still describe the file accurately?

### Reuse
Could the requested behavior fit naturally into existing code instead of adding another layer?

### Project map
Does `code-map.yaml` exactly match the Python structure?

### Architecture
Does `ARCHITECTURE.md` still describe the real system?

---

## 29. Required Completion Checklist

```text
[ ] Read ARCHITECTURE.md before changing Python architecture.
[ ] Read code-map.yaml before changing Python functions/files.
[ ] Created new files only when justified.
[ ] Avoided unnecessary tiny helper functions.
[ ] Avoided oversized mixed-responsibility functions.
[ ] Used clear function names.
[ ] No project function begins with "_".
[ ] Added readable parameter types.
[ ] Added return types where practical.
[ ] Simplified unnecessarily complex type annotations.
[ ] Avoided excessive function parameters.
[ ] Did not add "*" keyword-only separators.
[ ] Kept all imports at file top.
[ ] Centralized payload/parameter/config validation.
[ ] Added/updated concise function docstrings.
[ ] Added/updated accurate module-level descriptions.
[ ] Removed duplicate, unused, or dead code.
[ ] Did not silently swallow exceptions.
[ ] Safely cleaned up external resources.
[ ] Updated code-map.yaml for affected files/functions.
[ ] Updated ARCHITECTURE.md when architecture or flow changed.
[ ] Ran available syntax/tests/lint verification.
```

---

## 30. Agent Execution Rule

When this skill is active, follow this sequence:

```text
1. Read ARCHITECTURE.md.
2. Read code-map.yaml.
3. Inspect only the relevant implementation files.
4. Identify the current owner of the requested responsibility.
5. Prefer extending existing code over creating another abstraction.
6. Implement the smallest clear change.
7. Review function size and function count.
8. Review imports, typing, validation, naming, and docstrings.
9. Update code-map.yaml.
10. Update ARCHITECTURE.md when required.
11. Run available verification.
12. Report meaningful code and architecture changes.
```

The goal is not to minimize line count at all costs.

The goal is to minimize unnecessary complexity while keeping the implementation obvious, reusable, maintainable, and easy for future Codex agents to understand.
