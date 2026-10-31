"""Persist project-scoped records and atomic admissions in local SQLite."""

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path


def canonical(value: dict) -> str:
    """Encode records deterministically for durable conflict detection."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


class Store:
    """Use independent connections so claims remain safe across threads/processes."""

    def __init__(self, path: str | Path):
        """Create the local database and its project-scoped record table."""
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.execute(
                "CREATE TABLE IF NOT EXISTS records (namespace TEXT, project_id TEXT, key TEXT, value TEXT NOT NULL, PRIMARY KEY(namespace, project_id, key))"
            )

    @contextmanager
    def connect(self):
        """Open a bounded-wait connection; callers own its context and closure."""
        db = sqlite3.connect(str(self.path), timeout=15)
        try:
            with db:
                yield db
        finally:
            db.close()

    def put(self, namespace: str, project_id: str, key: str, value: dict) -> None:
        """Replace one scoped record atomically."""
        with self.connect() as db:
            db.execute(
                "INSERT INTO records VALUES (?,?,?,?) ON CONFLICT(namespace, project_id, key) DO UPDATE SET value=excluded.value",
                (namespace, project_id, key, canonical(value)),
            )

    def get(self, namespace: str, project_id: str, key: str) -> dict | None:
        """Read one scoped record without crossing project boundaries."""
        with self.connect() as db:
            row = db.execute(
                "SELECT value FROM records WHERE namespace=? AND project_id=? AND key=?",
                (namespace, project_id, key),
            ).fetchone()
        return json.loads(row[0]) if row else None

    def list(self, namespace: str, project_id: str) -> list[dict]:
        """List records in deterministic key order within one project."""
        with self.connect() as db:
            rows = db.execute(
                "SELECT value FROM records WHERE namespace=? AND project_id=? ORDER BY key",
                (namespace, project_id),
            ).fetchall()
        return [json.loads(row[0]) for row in rows]

    def claim(self, namespace: str, project_id: str, key: str, payload: dict) -> tuple[dict, bool]:
        """Insert once, returning the original admission or rejecting changed input."""
        encoded = canonical(payload)
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            cursor = db.execute(
                "INSERT OR IGNORE INTO records VALUES (?,?,?,?)",
                (namespace, project_id, key, encoded),
            )
            row = db.execute(
                "SELECT value FROM records WHERE namespace=? AND project_id=? AND key=?",
                (namespace, project_id, key),
            ).fetchone()
            if row[0] != encoded:
                raise ValueError("idempotency key conflicts with admitted payload")
            return json.loads(row[0]), cursor.rowcount == 1

    def close(self) -> None:
        """Connections belong to individual operations; there is no shared handle."""
