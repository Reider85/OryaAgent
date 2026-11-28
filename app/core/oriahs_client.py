"""OriaHS HTTP client — PROD bootstrap (P-00).

Single direct seam to the OriaHS REST backend (``settings.oriahs_url``).
The sibling OriaHS service is REST-only: readiness lives at
``GET /health/ready``, search returns ``hits`` (not ``results``) and both
``/search`` and ``/index`` require ``tenant_id``. This module translates
that contract for the ``oriahs_health`` tool, the readiness endpoint and
the ``oriahs-mcp`` wrapper, so the knowledge stays in one place.

Failures degrade: :meth:`OriaHSClient.health` never raises, and the exact
fallback message is shared with ``oriahs_search``.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx

from app.core.config import get_settings

logger = logging.getLogger(__name__)

ORIAHS_FALLBACK_MESSAGE = "service unavailable, use grep"
DEFAULT_ORIAHS_TENANT_ID = "11111111-1111-1111-1111-111111111111"

_INDEXABLE_SUFFIXES = frozenset(
    {
        ".py",
        ".js",
        ".jsx",
        ".ts",
        ".tsx",
        ".go",
        ".rs",
        ".java",
        ".c",
        ".h",
        ".cpp",
        ".hpp",
        ".cs",
        ".rb",
        ".php",
        ".md",
        ".txt",
        ".yaml",
        ".yml",
        ".json",
        ".toml",
        ".html",
        ".css",
    }
)


@dataclass
class OriaHSHealth:
    """Result of an OriaHS readiness probe (never an exception)."""

    ok: bool
    status: str
    checks: dict[str, Any] = field(default_factory=dict)
    latency_ms: float = 0.0
    error: str | None = None


class OriaHSClient:
    """Async httpx client bound to ``settings.oriahs_url``."""

    def __init__(
        self,
        base_url: str,
        timeout_s: float = 30.0,
        tenant_id: str = DEFAULT_ORIAHS_TENANT_ID,
        token: str | None = None,
        max_retries: int = 3,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.tenant_id = tenant_id or DEFAULT_ORIAHS_TENANT_ID
        self.timeout_s = timeout_s
        self.max_retries = max(1, max_retries)
        self._owns_client = http_client is None
        if http_client is not None:
            self._http_client = http_client
        else:
            headers = {"Authorization": f"Bearer {token}"} if token else {}
            self._http_client = httpx.AsyncClient(
                base_url=self.base_url, headers=headers, timeout=timeout_s
            )

    @classmethod
    def from_settings(cls) -> OriaHSClient:
        """Build a client from the effective :class:`Settings`."""
        settings = get_settings()
        token = (
            settings.oriahs_token.get_secret_value()
            if settings.oriahs_token is not None
            else None
        )
        return cls(
            base_url=settings.oriahs_url,
            timeout_s=settings.oriahs_timeout_s,
            tenant_id=settings.oriahs_tenant_id,
            token=token,
            max_retries=settings.mcp_max_retries,
        )

    async def close(self) -> None:
        """Close the underlying httpx client when this instance owns it."""
        if self._owns_client:
            await self._http_client.aclose()

    async def health(self) -> OriaHSHealth:
        """Probe ``GET /health/ready``; a down service is a value, not a raise."""
        started = time.perf_counter()
        try:
            response = await self._http_client.get("/health/ready")
            body = response.json() if response.content else {}
            status = (
                str(body.get("status", "unknown"))
                if isinstance(body, dict)
                else "unknown"
            )
            checks = body.get("checks", {}) if isinstance(body, dict) else {}
            ok = response.status_code == 200 and status == "ready"
            return OriaHSHealth(
                ok=ok,
                status=status if ok else "unavailable",
                checks=checks if isinstance(checks, dict) else {},
                latency_ms=(time.perf_counter() - started) * 1000,
                error=None if ok else f"HTTP {response.status_code}",
            )
        except Exception as exc:
            logger.warning("OriaHS readiness probe failed: %s", exc)
            return OriaHSHealth(
                ok=False,
                status="unavailable",
                latency_ms=(time.perf_counter() - started) * 1000,
                error=str(exc),
            )

    async def _post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        """POST with bounded retry on transport errors and 5xx responses."""
        last_error: Exception | None = None
        for attempt in range(self.max_retries):
            try:
                response = await self._http_client.post(path, json=payload)
                if response.status_code >= 500 and attempt + 1 < self.max_retries:
                    last_error = httpx.HTTPStatusError(
                        f"HTTP {response.status_code}",
                        request=response.request,
                        response=response,
                    )
                else:
                    response.raise_for_status()
                    return response.json() if response.content else {}
            except (httpx.TransportError, httpx.HTTPStatusError) as exc:
                last_error = exc
            if attempt + 1 < self.max_retries:
                await asyncio.sleep(0.1 * (2**attempt))
        raise httpx.HTTPError(ORIAHS_FALLBACK_MESSAGE) from last_error

    @staticmethod
    def _map_hit(hit: dict[str, Any], rank: int) -> dict[str, Any]:
        """Map a fresh OriaHS ``SearchHit`` to the legacy tool shape."""
        attributes = hit.get("attributes") or {}
        if not isinstance(attributes, dict):
            attributes = {}
        raw_line = (
            attributes.get("line") or attributes.get("start_line") or hit.get("line")
        )
        try:
            line = int(raw_line) if raw_line is not None else None
        except (TypeError, ValueError):
            line = None
        return {
            "rank": rank,
            "score": hit.get("score", 0.0),
            "path": attributes.get("path")
            or attributes.get("file_path")
            or hit.get("path")
            or hit.get("title")
            or "unknown",
            "line": line,
            "content": hit.get("snippet") or hit.get("content") or "",
            "type": attributes.get("type")
            or attributes.get("language")
            or hit.get("type")
            or "unknown",
            "doc_id": str(hit.get("doc_id")) if hit.get("doc_id") else None,
        }

    async def search(
        self,
        query: str,
        top_k: int | None = None,
        filters: dict[str, Any] | None = None,
        rerank: bool | None = None,
        fusion: str | None = None,
        explain: bool | None = None,
    ) -> list[dict[str, Any]]:
        """Hybrid search against ``POST /search`` using the fresh schema."""
        settings = get_settings()
        effective_top_k = (
            settings.oriahs_search_top_k_default if top_k is None else top_k
        )
        if fusion is not None and fusion not in ("rrf", "weighted"):
            raise ValueError("fusion must be 'rrf' or 'weighted'")
        payload: dict[str, Any] = {
            "query": query,
            "tenant_id": self.tenant_id,
            "top_k": min(max(1, effective_top_k), settings.oriahs_search_top_k_max),
            "filters": filters or {},
            "fusion": (settings.oriahs_search_fusion if fusion is None else fusion),
            "rerank": (settings.oriahs_search_rerank if rerank is None else rerank),
            "explain": (settings.oriahs_search_explain if explain is None else explain),
            "timeout_ms": 5000,
        }
        body = await self._post("/search", payload)
        hits = body.get("hits", body.get("results", []))
        if not isinstance(hits, list):
            return []
        return [self._map_hit(hit, rank) for rank, hit in enumerate(hits, 1)]

    @staticmethod
    def _build_index_payload(
        path: Path, content: str, tenant_id: str
    ) -> dict[str, Any]:
        """Build the required ``IndexRequest`` for one file."""
        digest = hashlib.sha256(content.encode("utf-8")).hexdigest()[:16]
        return {
            "tenant_id": tenant_id,
            "external_ref": f"{path}:{digest}",
            "title": path.name,
            "content": content,
            "language": path.suffix.lstrip(".") or None,
            "attributes": {"path": str(path), "source": "oriahs_index"},
        }

    async def index_file(self, file_path: str | Path) -> dict[str, Any]:
        """Index a single file through ``POST /index``."""
        path = Path(file_path).resolve()
        if not path.is_file():
            raise ValueError(f"File does not exist: {file_path}")
        content = await asyncio.to_thread(
            path.read_text, encoding="utf-8", errors="replace"
        )
        body = await self._post(
            "/index", self._build_index_payload(path, content, self.tenant_id)
        )
        return {
            "path": str(path),
            "status": body.get("status", "success"),
            "message": "File indexed successfully",
            "doc_id": body.get("doc_id"),
            "wait_for_index_token": body.get("wait_for_index_token"),
            "indexed_at": body.get("indexed_at"),
        }

    async def index_directory(
        self, directory_path: str | Path, recursive: bool = False
    ) -> dict[str, Any]:
        """Index indexable files in a directory, aggregating per-file status."""
        root = Path(directory_path).resolve()
        if not root.is_dir():
            raise ValueError(f"Directory does not exist: {directory_path}")
        candidates = root.rglob("*") if recursive else root.glob("*")
        files = [
            path
            for path in candidates
            if path.is_file() and path.suffix.lower() in _INDEXABLE_SUFFIXES
        ]
        indexed: list[dict[str, Any]] = []
        for path in files:
            try:
                indexed.append(await self.index_file(path))
            except Exception as exc:
                logger.warning("OriaHS index failed for %s: %s", path, exc)
                indexed.append(
                    {"path": str(path), "status": "error", "error": str(exc)}
                )
        return {
            "directory": str(root),
            "status": "success",
            "recursive": recursive,
            "indexed_files": len(
                [item for item in indexed if item.get("status") != "error"]
            ),
            "results": indexed,
        }

    async def wait_index(self, token: str) -> dict[str, Any]:
        """Poll ``GET /index/status/{token}`` for read-your-writes indexing."""
        response = await self._http_client.get(f"/index/status/{token}")
        response.raise_for_status()
        return response.json()

    async def delete(self, doc_id: str) -> bool:
        """Delete a document through ``DELETE /index/{doc_id}``."""
        response = await self._http_client.delete(f"/index/{doc_id}")
        return response.status_code in (200, 204)


_oriahs_client: OriaHSClient | None = None


def get_oriahs_client() -> OriaHSClient:
    """Return the process-wide OriaHS client, creating it on first use."""
    global _oriahs_client
    if _oriahs_client is None:
        _oriahs_client = OriaHSClient.from_settings()
    return _oriahs_client


async def close_oriahs_client() -> None:
    """Close the process-wide OriaHS client on shutdown."""
    global _oriahs_client
    if _oriahs_client is not None:
        await _oriahs_client.close()
        _oriahs_client = None


async def reset_oriahs_client(client: OriaHSClient | None = None) -> None:
    """Replace the cached client (used by tests and reconfiguration)."""
    global _oriahs_client
    await close_oriahs_client()
    _oriahs_client = client
