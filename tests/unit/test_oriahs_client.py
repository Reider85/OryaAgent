"""Unit tests for P-00 — the shared OriaHS HTTP client and fresh REST contract."""

from __future__ import annotations

import json
import os
from pathlib import Path

import httpx
import pytest

from app.core.config import clear_settings_cache
from app.core.oriahs_client import (
    ORIAHS_FALLBACK_MESSAGE,
    OriaHSClient,
    OriaHSHealth,
)


@pytest.fixture
def isolated_config(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """Sandbox env/config like every settings-touching test (AGENTS.md)."""
    for name in list(os.environ):
        if (
            name.startswith("ORYA_")
            or name.startswith("ORIAHS_")
            or name.startswith("MCP_")
        ):
            monkeypatch.delenv(name, raising=False)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("ORYA_CONFIG_PATH", str(tmp_path / "config.yaml"))
    clear_settings_cache()
    yield
    clear_settings_cache()


def _client(handler) -> tuple[httpx.AsyncClient, OriaHSClient]:
    """Build an injected-client pair; the transport owns no real socket."""
    http = httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="http://oriahs.test"
    )
    return http, OriaHSClient(
        base_url="http://oriahs.test", tenant_id="tenant-1", http_client=http
    )


async def test_health_ready_ok():
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.path)
        return httpx.Response(
            200, json={"status": "ready", "checks": {"postgres": "ok"}}
        )

    http, client = _client(handler)
    async with http:
        result = await client.health()

    assert seen == ["/health/ready"]
    assert result.ok is True
    assert result.status == "ready"
    assert result.checks == {"postgres": "ok"}
    assert result.latency_ms >= 0
    assert result.error is None


async def test_health_503_is_degraded_not_an_exception():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            503, json={"status": "degraded", "checks": {"qdrant": "fail"}}
        )

    http, client = _client(handler)
    async with http:
        result = await client.health()

    assert isinstance(result, OriaHSHealth)
    assert result.ok is False
    assert result.status == "unavailable"
    assert result.error == "HTTP 503"


async def test_health_transport_error_is_swallowed():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("backend down")

    http, client = _client(handler)
    async with http:
        result = await client.health()

    assert result.ok is False
    assert "backend down" in (result.error or "")


async def test_search_uses_fresh_schema_and_maps_hits():
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["path"] = request.url.path
        captured["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "hits": [
                    {
                        "doc_id": "abc",
                        "score": 0.91,
                        "title": "app/main.py",
                        "snippet": "def main(): pass",
                        "attributes": {"path": "app/main.py", "type": "python"},
                    }
                ]
            },
        )

    http, client = _client(handler)
    async with http:
        results = await client.search("main", top_k=5, filters={"language": "py"})

    assert captured["path"] == "/search"
    body = captured["body"]
    assert body["tenant_id"] == "tenant-1"
    assert body["query"] == "main"
    assert body["top_k"] == 5
    assert body["filters"] == {"language": "py"}
    assert "mode" not in body
    assert len(results) == 1
    assert results[0] == {
        "rank": 1,
        "score": 0.91,
        "path": "app/main.py",
        "content": "def main(): pass",
        "type": "python",
        "doc_id": "abc",
    }


async def test_search_accepts_legacy_results_shape():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "results": [
                    {
                        "score": 0.75,
                        "path": "legacy.py",
                        "content": "old shape",
                        "type": "function",
                    }
                ]
            },
        )

    http, client = _client(handler)
    async with http:
        results = await client.search("legacy")

    assert results[0]["path"] == "legacy.py"
    assert results[0]["content"] == "old shape"
    assert results[0]["type"] == "function"


async def test_index_file_sends_required_fields(tmp_path: Path):
    path = tmp_path / "sample.py"
    path.write_text("print('ok')\n", encoding="utf-8")
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content)
        return httpx.Response(
            201, json={"status": "queued", "doc_id": "d1", "indexed_at": "now"}
        )

    http, client = _client(handler)
    async with http:
        result = await client.index_file(path)

    body = captured["body"]
    assert body["tenant_id"] == "tenant-1"
    assert body["title"] == "sample.py"
    assert body["content"] == "print('ok')\n"
    assert body["external_ref"].startswith(str(path))
    assert "language" in body
    assert "operation" not in body
    assert result["status"] == "queued"
    assert result["doc_id"] == "d1"


async def test_post_retries_transient_5xx():
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls < 3:
            return httpx.Response(500, json={"error": "busy"})
        return httpx.Response(200, json={"hits": []})

    http, client = _client(handler)
    async with http:
        result = await client.search("retry")

    assert calls == 3
    assert result == []


async def test_from_settings_uses_unified_source(
    isolated_config, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setenv("ORYA_ORIAHS_URL", "http://fresh-OriaHS.local:9000")
    monkeypatch.setenv("ORYA_ORIAHS_TENANT_ID", "tenant-from-env")
    clear_settings_cache()

    client = OriaHSClient.from_settings()
    try:
        assert client.base_url == "http://fresh-OriaHS.local:9000"
        assert client.tenant_id == "tenant-from-env"
    finally:
        await client.close()


async def test_fallback_message_is_exact():
    assert ORIAHS_FALLBACK_MESSAGE == "service unavailable, use grep"
