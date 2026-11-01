"""Unit tests for A-15 — Langfuse OTLP/HTTP JSON exporter.

Covers the SpanRecord → OTLP mapping (ids, timestamps, gen_ai.* enrichment),
endpoint resolution, auto-on enablement, the queued delivery path (retry,
cooldown, direct fail-open), and the ``_finalize`` → ``export_span`` hook.
No network: the exporter's ``post`` seam is injected, settings are
sandboxed per the repo convention (chdir + env cleanup + cache clear).
"""

from __future__ import annotations

import base64
import json
import os
from pathlib import Path

import pytest

from app.core.config import clear_settings_cache
from app.core.observability import langfuse as lf
from app.core.observability.spans import (
    SpanRecord,
    clear_span_buffer,
    emit_span,
)

_MANAGED_ENV_VARS = frozenset(
    {
        "LANGFUSE_HOST",
        "LANGFUSE_PUBLIC_KEY",
        "LANGFUSE_SECRET_KEY",
        "LANGFUSE_DIRECT_URL",
        "LANGFUSE_EXPORT_ENABLED",
        "OTEL_EXPORTER_OTLP_ENDPOINT",
    }
)


@pytest.fixture(autouse=True)
def isolated(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """Sandbox env/config and reset the exporter singleton + counters."""
    for name in list(os.environ):
        if name.startswith("ORYA_") or name in _MANAGED_ENV_VARS:
            monkeypatch.delenv(name, raising=False)
    monkeypatch.chdir(tmp_path)  # ignore any project-root .env
    monkeypatch.setenv("ORYA_CONFIG_PATH", str(tmp_path / "config.yaml"))
    clear_settings_cache()
    lf.reset_exporter()
    lf.reset_export_stats()
    clear_span_buffer()
    yield
    lf.reset_exporter()
    lf.reset_export_stats()
    clear_span_buffer()
    clear_settings_cache()


def _record(
    *,
    span_type: str = "llm.call",
    status: str = "ok",
    trace_id: str = "a" * 32,
    span_id: str = "b" * 16,
    start_time: float = 1000.0,
    end_time: float | None = 1000.5,
    provider: str = "anthropic",
    model: str = "claude-sonnet-3.5",
    attributes: dict | None = None,
) -> SpanRecord:
    record = SpanRecord(
        provider=provider,
        model=model,
        trace_id=trace_id,
        span_id=span_id,
        start_time=start_time,
        span_type=span_type,
        status=status,
        attributes=attributes if attributes is not None else {},
    )
    record.end_time = end_time
    return record


# --- OTLP mapping ---------------------------------------------------------


def test_span_to_otlp_ids_timestamps_and_status():
    record = _record(status="error", attributes={"error.type": "ValueError"})
    otlp = lf.span_to_otlp(record)

    assert otlp["traceId"] == "a" * 32
    assert otlp["spanId"] == "b" * 16
    assert otlp["startTimeUnixNano"] == str(int(1000.0 * 1_000_000_000))
    assert otlp["endTimeUnixNano"] == str(int(1000.5 * 1_000_000_000))
    assert otlp["status"] == {"code": 2}  # ERROR
    assert otlp["kind"] == 3  # CLIENT for llm.call
    attrs = {a["key"]: a["value"] for a in otlp["attributes"]}
    assert attrs["error.type"] == {"stringValue": "ValueError"}
    assert attrs["status"] == {"stringValue": "error"}
    assert attrs["orya.span_type"] == {"stringValue": "llm.call"}


def test_span_to_otlp_gen_ai_enrichment_for_llm_calls():
    record = _record(
        attributes={
            "tokens.input": 11,
            "tokens.output": 22,
            "cost.usd": 0.004,
        }
    )
    attrs = {a["key"]: a["value"] for a in lf.span_to_otlp(record)["attributes"]}

    assert attrs["llm.provider"] == {"stringValue": "anthropic"}
    assert attrs["llm.model"] == {"stringValue": "claude-sonnet-3.5"}
    assert attrs["gen_ai.operation.name"] == {"stringValue": "chat"}
    assert attrs["gen_ai.request.model"] == {"stringValue": "claude-sonnet-3.5"}
    assert attrs["gen_ai.usage.input_tokens"] == {"intValue": 11}
    assert attrs["gen_ai.usage.output_tokens"] == {"intValue": 22}
    assert attrs["gen_ai.usage.cost"] == {"doubleValue": 0.004}


def test_span_to_otlp_permission_span_stays_internal():
    record = _record(
        span_type="agent.permission",
        provider="",
        model="",
        attributes={"permission.tool": "write"},
    )
    otlp = lf.span_to_otlp(record)
    attrs = {a["key"] for a in otlp["attributes"]}

    assert otlp["kind"] == 1  # INTERNAL
    assert "gen_ai.operation.name" not in attrs
    assert "permission.tool" in attrs


def test_span_to_otlp_a16_custom_spans_stay_internal():
    """A-16: agent.loop/tool.call/memory.write export as INTERNAL spans."""
    for span_type, extra in (
        ("agent.loop", {"agent.id": "orya-agent", "task.input": "hi"}),
        ("tool.call", {"tool.name": "echo", "tool.input_summary": "x"}),
        ("memory.write", {"memory.file": "FACTS.md", "memory.source": "learn"}),
    ):
        record = _record(
            span_type=span_type,
            provider="",
            model="",
            attributes=extra,
        )
        otlp = lf.span_to_otlp(record)
        attrs = {a["key"]: a["value"] for a in otlp["attributes"]}

        assert otlp["kind"] == 1, span_type  # INTERNAL
        assert attrs["orya.span_type"] == {"stringValue": span_type}
        for key in extra:
            assert key in attrs, f"{key} missing on {span_type}"


def test_otlp_id_sanitization_fallbacks():
    # Foreign (non-hex) trace ids fall back to a deterministic sha256 slice.
    hashed = lf._otlp_trace_id("turn-trace-xyz")
    assert len(hashed) == 32
    int(hashed, 16)
    assert hashed == lf._otlp_trace_id("turn-trace-xyz")
    assert hashed != lf._otlp_trace_id("turn-trace-abc")
    # Legacy 32-hex span ids are truncated to the W3C 16-hex width.
    assert lf._otlp_span_id("c" * 32) == "c" * 16
    assert lf._otlp_span_id("turn-span") == lf._otlp_span_id("turn-span")
    assert len(lf._otlp_span_id("turn-span")) == 16


def test_build_otlp_payload_shape():
    payload = lf.build_otlp_payload([_record()])
    resource = payload["resourceSpans"][0]
    resource_attrs = {a["key"]: a["value"] for a in resource["resource"]["attributes"]}
    assert resource_attrs["service.name"] == {"stringValue": "orya-agent"}
    scope = resource["scopeSpans"][0]["scope"]
    assert scope["name"] == "app.core.observability"
    assert len(resource["scopeSpans"][0]["spans"]) == 1


# --- Config resolution ----------------------------------------------------


def test_resolve_traces_url_prefers_collector(monkeypatch: pytest.MonkeyPatch):
    from app.core.config import get_settings

    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://collector:4318/")
    monkeypatch.setenv("LANGFUSE_HOST", "http://langfuse:3000")
    clear_settings_cache()
    settings = get_settings()
    assert lf.resolve_traces_url(settings) == "http://collector:4318/v1/traces"


def test_resolve_traces_url_langfuse_appends_otlp_path(monkeypatch):
    from app.core.config import get_settings

    monkeypatch.setenv("LANGFUSE_HOST", "http://sampler-proxy:4321/")
    clear_settings_cache()
    assert (
        lf.resolve_traces_url(get_settings())
        == "http://sampler-proxy:4321/api/public/otel/v1/traces"
    )


def test_resolve_traces_url_none_without_config():
    from app.core.config import get_settings

    assert lf.resolve_traces_url(get_settings()) is None


def test_is_configured_requires_host_and_keys(monkeypatch):
    from app.core.config import get_settings

    assert lf._is_configured(get_settings()) is False

    monkeypatch.setenv("LANGFUSE_HOST", "http://lf:3000")
    clear_settings_cache()
    assert lf._is_configured(get_settings()) is False  # keys missing

    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk")
    clear_settings_cache()
    assert lf._is_configured(get_settings()) is True

    monkeypatch.setenv("ORYA_LANGFUSE_EXPORT_ENABLED", "false")
    clear_settings_cache()
    assert lf._is_configured(get_settings()) is False  # kill-switch


# --- Delivery path --------------------------------------------------------


def test_send_batch_posts_otlp_json_with_basic_auth():
    captured: dict = {}

    def post(url, headers, body):
        captured["url"] = url
        captured["headers"] = headers
        captured["body"] = body

    url = "http://lf:3000/api/public/otel/v1/traces"
    auth = base64.b64encode(b"pk:sk").decode()
    exporter = lf.LangfuseOtlpExporter(url, auth, post=post)
    exporter.send_batch([_record()])

    assert captured["url"] == url
    assert captured["headers"]["Authorization"] == f"Basic {auth}"
    payload = json.loads(captured["body"])
    assert payload["resourceSpans"][0]["scopeSpans"][0]["spans"][0]["spanId"]

    stats = lf.get_export_stats()
    assert stats["exported_total"] == 1
    assert stats["failed_total"] == 0


def test_send_batch_retries_then_falls_back_to_direct():
    attempts: list[str] = []

    def post(url, headers, body):
        attempts.append(url)
        if url == "http://proxy:4321/api/public/otel/v1/traces":
            raise lf._RetryableError("proxy down")

    primary = "http://proxy:4321/api/public/otel/v1/traces"
    direct = "http://langfuse:3000/api/public/otel/v1/traces"
    exporter = lf.LangfuseOtlpExporter(
        primary, None, direct_url=direct, post=post, backoff_base_s=0.0
    )
    exporter.send_batch([_record()])

    assert attempts.count(primary) == lf.MAX_ATTEMPTS
    assert attempts[-1] == direct
    stats = lf.get_export_stats()
    assert stats["exported_total"] == 1
    assert stats["failed_total"] == 0


def test_send_batch_permanent_error_is_not_retried():
    calls: list[str] = []

    def post(url, headers, body):
        calls.append(url)
        raise lf._PermanentError("HTTP 401")

    direct = "http://langfuse:3000/api/public/otel/v1/traces"
    exporter = lf.LangfuseOtlpExporter(
        "http://proxy:4321/x", None, direct_url=direct, post=post
    )
    exporter.send_batch([_record()])

    assert len(calls) == 1  # no retries, no direct fallback on 4xx
    stats = lf.get_export_stats()
    assert stats["failed_total"] == 1
    assert stats["exported_total"] == 0


def test_cooldown_drops_after_repeated_failures():
    def post(url, headers, body):
        raise lf._RetryableError("down")

    exporter = lf.LangfuseOtlpExporter(
        "http://proxy:4321/x", None, post=post, backoff_base_s=0.0
    )
    for _ in range(lf.COOLDOWN_AFTER_FAILURES):
        exporter.send_batch([_record()])

    # Cooldown armed: the next batch is dropped without a POST attempt.
    calls_before = 0
    exporter.send_batch([_record()])
    assert calls_before == 0
    stats = lf.get_export_stats()
    assert stats["failed_total"] == lf.COOLDOWN_AFTER_FAILURES + 1
    assert exporter._cooldown_until > 0


def test_offer_drops_when_queue_full():
    exporter = lf.LangfuseOtlpExporter("http://x/y", None, post=lambda *a: None)
    for _ in range(lf.QUEUE_MAX):
        exporter.offer(_record())
    exporter.offer(_record())  # dropped, never raises

    assert exporter.queued == lf.QUEUE_MAX
    assert lf.get_export_stats()["failed_total"] == 1


def test_flush_drains_queue_and_sends():
    posted: list[dict] = []

    def post(url, headers, body):
        posted.append(json.loads(body))

    exporter = lf.LangfuseOtlpExporter("http://x/y", None, post=post)
    exporter.offer(_record())
    exporter.offer(_record())
    exporter.flush(timeout=1.0)

    assert exporter.queued == 0
    spans = posted[0]["resourceSpans"][0]["scopeSpans"][0]["spans"]
    assert len(spans) == 2
    assert lf.get_export_stats()["exported_total"] == 2


def test_export_span_skips_when_unconfigured():
    lf.export_span(_record())
    assert lf.get_export_stats()["enabled"] is False
    assert lf.get_export_stats()["queued"] == 0
    assert lf.get_exporter() is None


def test_finalize_feeds_exporter_when_configured(monkeypatch):
    """The emit path (_finalize) offers records to the active exporter."""

    monkeypatch.setenv("LANGFUSE_HOST", "http://lf:3000")
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk")
    clear_settings_cache()

    posted: list[dict] = []

    def post(url, headers, body):
        posted.append(json.loads(body))

    exporter = lf.LangfuseOtlpExporter(
        "http://lf:3000/api/public/otel/v1/traces", None, post=post
    )
    lf._exporter = exporter  # install the singleton directly (no thread)

    try:
        emit_span(
            span_type="agent.permission",
            name="agent.permission:write",
            attributes={"permission.tool": "write"},
            status="ok",
        )
        assert exporter.queued == 1
        exporter.flush(timeout=1.0)
        spans = posted[0]["resourceSpans"][0]["scopeSpans"][0]["spans"]
        assert spans[0]["name"] == "agent.permission:write"
    finally:
        lf.reset_exporter()
        clear_settings_cache()


def test_shutdown_exporter_is_idempotent_and_never_raises():
    lf.shutdown_exporter()
    lf.shutdown_exporter()
    lf.reset_exporter()
