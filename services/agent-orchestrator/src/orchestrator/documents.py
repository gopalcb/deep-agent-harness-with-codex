"""Publish completed Markdown through an explicit authenticated lab API contract.

This is an integration boundary, not a claim of compatibility with any existing
private API. A receipt must bind project, idempotency key and submitted hash.
"""

import hashlib
from pathlib import PurePosixPath
from urllib.parse import urlsplit

import httpx

from orchestrator.storage import Store


def validate_document_path(path: str) -> str:
    """Allow relative Markdown artifact paths and reject traversal or aliases."""
    parsed = PurePosixPath(path)
    if (
        not path
        or parsed.is_absolute()
        or "\\" in path
        or ".." in parsed.parts
        or not path.endswith(".md")
        or str(parsed) != path
    ):
        raise ValueError("path must be a normalized relative Markdown path")
    return path


class MarkdownPublisher:
    """Journal admission before sending; uncertain writes require explicit reconciliation."""

    def __init__(self, store: Store, base_url: str, token: str, client: httpx.Client | None = None):
        """Require authentication and HTTPS except explicit loopback development."""
        url = urlsplit(base_url)
        if (
            not token.strip()
            or not url.hostname
            or url.username
            or url.password
            or url.query
            or url.fragment
            or (
                url.scheme != "https"
                and not (url.scheme == "http" and url.hostname in {"localhost", "127.0.0.1", "::1"})
            )
        ):
            raise ValueError("authenticated HTTPS or loopback endpoint required")
        self.store, self.base_url, self.token = store, base_url.rstrip("/"), token
        self.client = client or httpx.Client(timeout=20, follow_redirects=False)
        self.owns_client = client is None

    def publish(
        self,
        project_id: str,
        run_id: str,
        path: str,
        content: str,
        idempotency_key: str,
        metadata: dict | None = None,
    ) -> dict:
        """Send an admitted revision once and validate its exact READY receipt."""
        validate_document_path(path)
        if not project_id or not run_id or not idempotency_key or not content.strip():
            raise ValueError("project, run, key and nonempty Markdown are required")
        digest = hashlib.sha256(content.encode()).hexdigest()
        payload = {
            "project_id": project_id,
            "run_id": run_id,
            "path": path,
            "content": content,
            "content_type": "text/markdown",
            "idempotency_key": idempotency_key,
            "content_hash": digest,
            "metadata": metadata or {},
        }
        admission = {
            "run_id": run_id,
            "path": path,
            "content_hash": digest,
            "metadata": metadata or {},
        }
        _, created = self.store.claim("document_admissions", project_id, idempotency_key, admission)
        if not created:
            return self.store.get("document_receipts", project_id, idempotency_key) or {
                "status": "uncertain",
                **admission,
            }
        self.store.put(
            "document_receipts", project_id, idempotency_key, {"status": "uncertain", **admission}
        )
        try:
            response = self.client.post(
                f"{self.base_url}/documents",
                json=payload,
                headers={
                    "Authorization": f"Bearer {self.token}",
                    "Idempotency-Key": idempotency_key,
                },
            )
            response.raise_for_status()
            return self.accept_receipt(project_id, idempotency_key, response.json())
        except (httpx.HTTPError, ValueError, KeyError):
            # A server may have committed despite an invalid/absent response. No automatic retry.
            return self.store.get("document_receipts", project_id, idempotency_key)

    def accept_receipt(self, project_id: str, key: str, receipt: dict) -> dict:
        """Validate a receipt against its immutable revision before marking delivery."""
        admission = self.store.get("document_admissions", project_id, key)
        if (
            not isinstance(receipt, dict)
            or not admission
            or receipt.get("status") != "READY"
            or not isinstance(receipt.get("document_id"), str)
            or not receipt["document_id"].strip()
            or receipt.get("project_id") != project_id
            or receipt.get("idempotency_key") != key
            or receipt.get("content_hash") != admission["content_hash"]
        ):
            raise ValueError("receipt does not verify the exact admitted document")
        result = {
            **admission,
            "status": "READY",
            "document_id": receipt["document_id"],
            "s3_version_id": receipt.get("s3_version_id"),
        }
        self.store.put("document_receipts", project_id, key, result)
        return result

    def reconcile(self, project_id: str, idempotency_key: str) -> dict:
        """Query an authenticated receipt endpoint without repeating the original write."""
        response = self.client.get(
            f"{self.base_url}/documents/receipt",
            params={"project_id": project_id, "idempotency_key": idempotency_key},
            headers={"Authorization": f"Bearer {self.token}"},
        )
        response.raise_for_status()
        return self.accept_receipt(project_id, idempotency_key, response.json())

    def search(self, project_id: str, query: str) -> list[dict]:
        """Search the configured service with mandatory project scope."""
        response = self.client.get(
            f"{self.base_url}/documents",
            params={"project_id": project_id, "q": query},
            headers={"Authorization": f"Bearer {self.token}"},
        )
        response.raise_for_status()
        items = response.json()
        if not isinstance(items, list) or any(
            not isinstance(item, dict) or item.get("project_id") != project_id for item in items
        ):
            raise ValueError("search returned an invalid project scope")
        return items

    def close(self) -> None:
        """Close only the transport owned by this publisher."""
        if self.owns_client:
            self.client.close()
