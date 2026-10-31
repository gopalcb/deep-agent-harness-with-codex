"""Load loopback service configuration without exposing internal credentials."""

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass
class Settings:
    """Runtime paths and authenticated service boundaries."""

    token: str
    data_dir: Path
    codex_url: str = "http://127.0.0.1:3100"
    mode: str = "demo"
    project_id: str = "lab"
    model: str | None = None
    context_capacity: int = 32000


def load_settings() -> Settings:
    """Fail closed when the required internal service credential is absent."""
    token = os.environ.get("LAB_INTERNAL_TOKEN", "")
    if not token:
        raise ValueError("LAB_INTERNAL_TOKEN is required")
    return Settings(
        token=token,
        data_dir=Path(os.environ.get("LAB_DATA_DIR", ".lab-data")),
        codex_url=os.environ.get("CODEX_BASE_URL", "http://127.0.0.1:3100"),
        mode=os.environ.get("LAB_MODE", "demo"),
        project_id=os.environ.get("LAB_PROJECT_ID", "lab"),
        model=os.environ.get("LAB_PLANNER_MODEL"),
        context_capacity=int(os.environ.get("LAB_CONTEXT_CAPACITY", "32000")),
    )
