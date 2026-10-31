"""Collect correlated redacted events with SQLite replay and recoverable JSONL export."""

import hashlib
import json
import os
import re
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from orchestrator.contracts import Event
from orchestrator.storage import Store, canonical

SECRET_KEY = re.compile(
    r"password|secret|token|authorization|api.?key|cookie|credential|otp", re.IGNORECASE
)
SECRET_TEXT = re.compile(
    r"Bearer\s+[^\s\"']+|\bsk-[A-Za-z0-9_-]+|\b(?:access_token|refresh_token|password|api_key)\s*[=:]\s*[^\s&]+",
    re.IGNORECASE,
)


def redact(value: object) -> object:
    """Remove secret fields and recognizable credentials before persistence/export."""
    if isinstance(value, dict):
        return {
            key: "[REDACTED]"
            if SECRET_KEY.search(str(key))
            and not (str(key).endswith("_tokens") and isinstance(item, (int, float)))
            else redact(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [redact(item) for item in value]
    if isinstance(value, str):
        return SECRET_TEXT.sub("[REDACTED]", value)
    return value


class EventCollector:
    """Make SQLite authoritative and rebuild rotating exports after interrupted writes."""

    def __init__(self, store: Store, directory: Path, max_bytes: int = 1_000_000):
        """Initialize the durable sequence and repair export files on restart."""
        if max_bytes < 256:
            raise ValueError("max_bytes must be at least 256")
        self.store, self.directory, self.max_bytes = store, Path(directory), max_bytes
        self.directory.mkdir(parents=True, exist_ok=True)
        with store.connect() as db:
            db.execute(
                "CREATE TABLE IF NOT EXISTS events (sequence INTEGER PRIMARY KEY AUTOINCREMENT, event_id TEXT UNIQUE NOT NULL, project_id TEXT NOT NULL, run_id TEXT NOT NULL, digest TEXT NOT NULL, envelope TEXT NOT NULL)"
            )
            db.execute("BEGIN IMMEDIATE")
            self.export(db)

    def append(self, event: Event | dict) -> dict:
        """Validate, deduplicate and redact an event before durable storage."""
        payload = Event.model_validate(event).model_dump()
        payload["duration_ms"] = float(payload["duration_ms"])
        digest = hashlib.sha256(canonical(payload).encode()).hexdigest()
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT digest, envelope FROM events WHERE event_id=?", (payload["event_id"],)
            ).fetchone()
            if row:
                if row[0] != digest:
                    raise ValueError("event_id conflicts with existing event")
                return json.loads(row[1])
            envelope = redact(payload)
            cursor = db.execute(
                "INSERT INTO events(event_id, project_id, run_id, digest, envelope) VALUES(?,?,?,?,?)",
                (payload["event_id"], payload["project_id"], payload["run_id"], digest, "{}"),
            )
            envelope["sequence"] = cursor.lastrowid
            db.execute(
                "UPDATE events SET envelope=? WHERE sequence=?",
                (canonical(envelope), cursor.lastrowid),
            )
            self.export(db)
        return envelope

    def export(self, db: object) -> None:
        """Atomically replace each rotated file using database order under its write lock."""
        pages, page, size = [], [], 0
        for (encoded,) in db.execute("SELECT envelope FROM events ORDER BY sequence"):
            line = encoded + "\n"
            if page and size + len(line.encode()) > self.max_bytes:
                pages.append("".join(page))
                page, size = [], 0
            page.append(line)
            size += len(line.encode())
        if page:
            pages.append("".join(page))
        for index, content in enumerate(pages):
            target = self.directory / f"events-{index:06d}.jsonl"
            temporary = target.with_suffix(".tmp")
            with temporary.open("w", encoding="utf-8") as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            temporary.replace(target)
        for stale in self.directory.glob("events-*.jsonl"):
            if int(stale.stem.split("-")[1]) >= len(pages):
                stale.unlink()

    def replay(self, project_id: str, run_id: str, after: int = 0, limit: int = 200) -> list[dict]:
        """Replay one correlated stream after a durable global cursor."""
        with self.store.connect() as db:
            rows = db.execute(
                "SELECT envelope FROM events WHERE project_id=? AND run_id=? AND sequence>? ORDER BY sequence LIMIT ?",
                (project_id, run_id, after, min(max(limit, 1), 1000)),
            ).fetchall()
        return [json.loads(row[0]) for row in rows]

    def emit(
        self,
        project_id: str,
        run_id: str,
        event_type: str,
        metadata: dict | None = None,
        **fields: object,
    ) -> dict:
        """Create a timestamped correlated envelope and append it once."""
        return self.append(
            {
                "event_id": str(uuid4()),
                "project_id": project_id,
                "run_id": run_id,
                "timestamp": datetime.now(UTC).isoformat(),
                "event_type": event_type,
                "metadata": metadata or {},
                **fields,
            }
        )
