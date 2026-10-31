"""Keep candidate knowledge separate from reviewed, evidence-backed project memory."""

from datetime import UTC, datetime
from uuid import uuid4

from orchestrator.events import redact
from orchestrator.storage import Store


class MemoryStore:
    """Retrieve only current, reviewed, verified facts from the requested project."""

    def __init__(self, store: Store):
        """Share the project's durable record store."""
        self.store = store

    def save_candidate(
        self, project_id: str, content: str, source: str, evidence: list[dict], expires_at: str
    ) -> dict:
        """Save untrusted extraction with provenance; never promote it implicitly."""
        expiry = datetime.fromisoformat(expires_at)
        if not content.strip() or not source.strip() or expiry.tzinfo is None:
            raise ValueError("content, provenance and timezone-aware expiry are required")
        candidate = {
            "id": str(uuid4()),
            "project_id": project_id,
            "content": redact(content),
            "source": redact(source),
            "evidence": redact(evidence),
            "expires_at": expiry.isoformat(),
            "created_at": datetime.now(UTC).isoformat(),
            "status": "candidate",
        }
        self.store.put("memory", project_id, candidate["id"], candidate)
        return candidate

    def promote(self, project_id: str, candidate_id: str, reviewed_by: str) -> dict:
        """Require explicit review and successful nonempty check evidence for promotion."""
        candidate = self.store.get("memory", project_id, candidate_id)
        if not candidate:
            raise KeyError(candidate_id)
        checks = candidate["evidence"]
        if (
            not reviewed_by.strip()
            or not checks
            or not all(check.get("passed") is True and check.get("source") for check in checks)
        ):
            raise ValueError("review and successful sourced evidence are required")
        if datetime.fromisoformat(candidate["expires_at"]) <= datetime.now(UTC):
            raise ValueError("expired knowledge cannot be promoted")
        candidate.update(status="verified", reviewed_by=reviewed_by)
        self.store.put("memory", project_id, candidate_id, candidate)
        return candidate

    def retrieve(self, project_id: str, query: str = "", limit: int = 10) -> list[dict]:
        """Filter expired/invalidated candidates and deduplicate verified content."""
        now, found, seen = datetime.now(UTC), [], set()
        for item in self.store.list("memory", project_id):
            if item["status"] != "verified" or datetime.fromisoformat(item["expires_at"]) <= now:
                continue
            if query.casefold() not in item["content"].casefold() or item["content"] in seen:
                continue
            seen.add(item["content"])
            found.append(item)
        return found[: min(max(limit, 0), 50)]

    def invalidate(self, project_id: str, candidate_id: str) -> None:
        """Remove superseded knowledge from future retrieval without losing provenance."""
        candidate = self.store.get("memory", project_id, candidate_id)
        if not candidate:
            raise KeyError(candidate_id)
        candidate["status"] = "invalidated"
        self.store.put("memory", project_id, candidate_id, candidate)
