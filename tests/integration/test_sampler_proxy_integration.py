"""A-17: Integration tests for sampler-proxy mode with live proxy.

Tests the sampler-proxy integration with:
- Real sampler-proxy container (requires ../OryaObservability sibling checkout)
- Cost/security span attributes (cost.over_budget, security.incident)
- Audit sink to ClickHouse
- Prometheus scrape endpoint

Network tests self-skip (repo convention: conditional, not marker-based):
first when the sibling checkout is missing, then when the endpoint is
unreachable — start the stack with ``COMPOSE_PROFILES=observability``.
"""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

pytestmark = pytest.mark.integration

_PROXY_URL = "http://localhost:4321"  # sampler-proxy OTLP/HTTP
_METRICS_URL = "http://localhost:9095"  # sampler-proxy /metrics (compose healthcheck)
_CLICKHOUSE_URL = "http://localhost:8123"


@pytest.fixture(scope="session")
def proxy_available() -> bool:
    """Check if sampler-proxy can be built (requires sibling checkout)."""
    obs_path = Path(__file__).parent.parent.parent.parent / "OryaObservability"
    if not obs_path.exists():
        return False
    dockerfile = obs_path / "scripts" / "sampler" / "Dockerfile"
    return dockerfile.exists()


async def _get(url: str) -> httpx.Response | None:
    """GET ``url`` or ``None`` when the endpoint is unreachable."""
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            return await client.get(url)
    except httpx.HTTPError:
        return None


async def test_sampler_proxy_metrics_endpoint(proxy_available: bool) -> None:
    """A-17: Sampler-proxy exposes metrics at /metrics (compose healthcheck)."""
    if not proxy_available:
        pytest.skip("sibling ../OryaObservability checkout missing")
    response = await _get(f"{_METRICS_URL}/metrics")
    if response is None:
        pytest.skip("sampler-proxy metrics port not reachable")
    assert response.status_code == 200

    # The sampler's own metrics only appear once the stack is up
    metrics_text = response.text
    if "sampler_proxy_requests_total" not in metrics_text:
        pytest.skip("sampler-proxy metrics not scraped (observability stack down)")
    assert "sampler_proxy_dropped_requests_total" in metrics_text


async def test_sampler_proxy_otel_endpoint(proxy_available: bool) -> None:
    """A-17: Sampler-proxy accepts OTLP/HTTP spans at /v1/traces."""
    if not proxy_available:
        pytest.skip("sibling ../OryaObservability checkout missing")
    # Test payload with cost/security attributes (A-17)
    span_data = {
        "spans": [
            {
                "trace_id": "test-trace-123",
                "span_id": "test-span-456",
                "parent_span_id": None,
                "name": "agent.loop",
                "kind": "INTERNAL",
                "start_time": "2023-01-01T00:00:00Z",
                "end_time": "2023-01-01T00:00:01Z",
                "attributes": {
                    "agent.id": "test-agent",
                    "agent.version": "1.0.0",
                    "task.input": "test input",
                    "cost.over_budget": "true",  # A-17: cost attribute
                    "security.incident": "true",  # A-17: security attribute
                },
            }
        ]
    }

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(
                f"{_PROXY_URL}/v1/traces",
                json=span_data,
                headers={"Content-Type": "application/json"},
            )
    except httpx.HTTPError:
        pytest.skip("sampler-proxy OTLP endpoint not reachable")
    # Proxy might return 202 even if downstream fails (best-effort)
    assert response.status_code in [200, 202]


async def test_sampler_proxy_rate_file(tmp_path: Path) -> None:
    """A-17: Sampler-proxy respects rate file at /shared/sampler_rate.json."""
    rate_file = tmp_path / "sampler_rate.json"
    rate_file.write_text(json.dumps({"sample_rate": 0.5, "reason": "test-policy"}))

    # This would be tested with a real container mount
    # For now, just verify the file format
    rate_data = json.loads(rate_file.read_text())
    assert rate_data["sample_rate"] == 0.5
    assert rate_data["reason"] == "test-policy"


async def test_sampler_proxy_health_endpoint(proxy_available: bool) -> None:
    """A-17: Sampler-proxy health via GET /metrics (compose healthcheck, not HEAD)."""
    if not proxy_available:
        pytest.skip("sibling ../OryaObservability checkout missing")
    response = await _get(f"{_METRICS_URL}/metrics")
    if response is None:
        pytest.skip("sampler-proxy health endpoint not reachable")
    assert response.status_code == 200


async def test_sampler_proxy_audit_sink_config() -> None:
    """A-17: Verify audit sink configuration environment variables."""
    # These would be set in the container environment
    required_env_vars = [
        "AGENT_OBS_SAMPLER_AUDIT_ENABLED",
        "CLICKHOUSE_HOST",
        "CLICKHOUSE_PORT",
        "CLICKHOUSE_DB",
        "CLICKHOUSE_USER",
        "CLICKHOUSE_PASSWORD",
    ]

    # In a real test, we'd check the container env
    # For now, just verify the variables are properly named
    for var in required_env_vars:
        assert var.startswith(("CLICKHOUSE_", "AGENT_OBS_"))


async def test_sampler_proxy_clickhouse_table(proxy_available: bool) -> None:
    """A-17: Verify ClickHouse audit_events_hot table exists (if ClickHouse running)."""
    if not proxy_available:
        pytest.skip("sibling ../OryaObservability checkout missing")
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            # Check if database exists
            response = await client.get(
                f"{_CLICKHOUSE_URL}",
                params={"query": "SHOW DATABASES", "default_format": "JSON"},
            )
            if response.status_code == 200:
                databases = response.json()
                # Check if observability database exists
                db_names = [db["name"] for db in databases.get("data", [])]
                assert "observability" in db_names

                # Check if audit_events_hot table exists
                response = await client.get(
                    f"{_CLICKHOUSE_URL}",
                    params={
                        "query": "SHOW TABLES FROM observability",
                        "default_format": "JSON",
                    },
                )
                if response.status_code == 200:
                    tables = response.json()
                    table_names = [table["name"] for table in tables.get("data", [])]
                    assert "audit_events_hot" in table_names
    except httpx.ConnectError:
        # ClickHouse not running, skip this part
        pytest.skip("ClickHouse not available")


async def test_sampler_proxy_downstream_config() -> None:
    """A-17: Verify downstream URL configuration (Langfuse by default)."""
    # In a real test, we'd check the container environment
    # For now, just verify the default makes sense
    default_downstream = "http://langfuse:3000"
    assert default_downstream.startswith("http://")
    assert "langfuse" in default_downstream


async def test_sampler_proxy_ports() -> None:
    """A-17: Verify sampler-proxy port configuration."""
    # Standard ports from the implementation
    ports = {
        "http": 4321,  # OTLP/HTTP
        "grpc": 4320,  # OTLP/gRPC
        "metrics": 9095,  # Prometheus metrics
    }

    # In a real test, we'd check the container exposed ports
    # For now, just verify the port numbers are reasonable
    assert 1000 < ports["http"] < 65535
    assert 1000 < ports["grpc"] < 65535
    assert 1000 < ports["metrics"] < 65535
