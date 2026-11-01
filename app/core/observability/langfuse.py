"""Langfuse OTLP/HTTP JSON exporter (A-15): finished spans → Langfuse.

Hand-rolled OTLP/HTTP JSON exporter — no OpenTelemetry SDK dependency,
following the same repo convention as the hand-rolled Prometheus
exposition in ``app/api/metrics.py``. Every finished span offered through
:func:`export_span` (called from ``spans._finalize`` for all span types —
``llm.call``, ``agent.permission``, ...) is queued and POSTed to
``{LANGFUSE_HOST}/api/public/otel/v1/traces`` with Basic auth. That path
works both against Langfuse directly and via the A-10 sampler-proxy,
which accepts any path and rewrites the downstream target itself. When
``OTEL_EXPORTER_OTLP_ENDPOINT`` is set it wins and is treated as a
generic OTLP collector base (``{endpoint}/v1/traces``).

Design (A-15):

- **Auto-on when configured**: export is effective only when
  ``ORYA_LANGFUSE_EXPORT_ENABLED`` (default true) AND ``LANGFUSE_HOST``
  AND both keys are present — bare host-process dev and the test-suite
  stay exporter-free.
- **Fail-soft**: ``export_span`` never raises and never blocks the
  agent-loop — records go into a bounded queue (drop-on-full) drained by
  a daemon worker thread. Retries use short backoff; after repeated
  failures the worker cools down instead of hammering a dead endpoint;
  ``LANGFUSE_DIRECT_URL`` is tried once per batch as a fail-open
  fallback. The FastAPI lifespan flushes the queue best-effort on
  shutdown (``shutdown_exporter``).
- **Trace fidelity**: OTLP ``traceId``/``spanId`` are the A-06 cross-link
  ids at W3C widths (32/16 hex), so the JSONL projection joins the same
  Langfuse trace the turn produced.
- **Langfuse-native rendering**: ``llm.call`` spans are enriched with
  ``gen_ai.*`` semantic-convention attributes (operation, model, usage,
  cost) so Langfuse v3 classifies them as GENERATION observations —
  the same mapping as the sibling ``agent_obs.exporters`` (P23).

Usage::

    from app.core.observability.langfuse import export_span, get_export_stats

    export_span(record)        # from spans._finalize; never raises
    get_export_stats()         # {enabled, queued, exported_total, failed_total}
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import queue
import threading
import time
from typing import TYPE_CHECKING, Any

import httpx

from app.core.config import get_settings

if TYPE_CHECKING:
    from app.core.observability.spans import SpanRecord

logger = logging.getLogger(__name__)

#: Bounded queue between the emit path and the worker thread.
QUEUE_MAX = 1000
#: Upper bound of one POSTed batch.
BATCH_MAX = 128
#: How long the worker blocks waiting for the first record of a batch.
WORKER_POLL_S = 0.5
#: Per-request timeout for the OTLP POST.
REQUEST_TIMEOUT_S = 5.0
#: Attempts against the primary endpoint (incl. the first) before fail-open.
MAX_ATTEMPTS = 3
#: Base delay of the retry backoff (seconds).
BACKOFF_BASE_S = 0.2
#: Consecutive failed batches before the cooldown kicks in.
COOLDOWN_AFTER_FAILURES = 3
#: Cooling-down window during which no export attempts are made.
COOLDOWN_S = 30.0

#: Langfuse's OTLP ingest path (appended to LANGFUSE_HOST / DIRECT_URL).
OTLP_PATH_LANGFUSE = "/api/public/otel/v1/traces"
#: Generic OTLP collector path (appended to OTEL_EXPORTER_OTLP_ENDPOINT).
OTLP_PATH_COLLECTOR = "/v1/traces"

_HEX_FROZEN = frozenset("0123456789abcdefABCDEF")

_stats_lock = threading.Lock()
_exported_spans_total = 0
_export_errors_total = 0

_service_version: str | None = None


class _RetryableError(Exception):
    """Transient export failure (network error, 429, 5xx) — worth a retry."""


class _PermanentError(Exception):
    """Non-retryable export failure (4xx other than 429) — drop the batch."""


# --- OTLP mapping ---------------------------------------------------------


def _otlp_trace_id(value: str) -> str:
    """W3C trace id (32 hex); deterministic sha256 fallback for foreign ids."""
    if len(value) == 32 and all(c in _HEX_FROZEN for c in value):
        return value.lower()
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:32]


def _otlp_span_id(value: str) -> str:
    """W3C span id (16 hex); truncates legacy 32-hex ids, hashes the rest."""
    if len(value) == 16 and all(c in _HEX_FROZEN for c in value):
        return value.lower()
    if len(value) > 16 and all(c in _HEX_FROZEN for c in value):
        return value[:16].lower()
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]


def _attr_value(value: Any) -> dict[str, Any]:
    """Python value → OTLP ``AnyValue`` (JSON encoding)."""
    if isinstance(value, bool):
        return {"boolValue": value}
    if isinstance(value, int):
        return {"intValue": value}
    if isinstance(value, float):
        return {"doubleValue": value}
    if isinstance(value, list):
        return {"arrayValue": {"values": [_attr_value(v) for v in value]}}
    return {"stringValue": str(value)}


def _status_code(status: str) -> int:
    """SpanRecord status → OTLP status code (UNSET=0, OK=1, ERROR=2)."""
    return {"ok": 1, "error": 2}.get(status, 0)


def span_to_otlp(record: SpanRecord) -> dict[str, Any]:
    """Convert one ``SpanRecord`` to an OTLP ``Span`` dict.

    ``llm.call`` spans get ``gen_ai.*`` enrichment (operation, model,
    usage, cost) so Langfuse v3 renders them as native GENERATION
    observations; every span keeps its original attributes plus
    ``status``/``orya.span_type`` for the UI metadata panel.
    """
    attrs: dict[str, Any] = dict(record.attributes)
    attrs.setdefault("status", record.status)
    if record.span_type:
        attrs.setdefault("orya.span_type", record.span_type)

    is_llm = record.span_type == "llm.call" or bool(record.provider and record.model)
    if is_llm:
        if record.provider:
            attrs.setdefault("llm.provider", record.provider)
        if record.model:
            attrs.setdefault("llm.model", record.model)
            attrs.setdefault("gen_ai.request.model", record.model)
        attrs.setdefault("gen_ai.operation.name", "chat")
        for source, convention in (
            ("tokens.input", "gen_ai.usage.input_tokens"),
            ("tokens.output", "gen_ai.usage.output_tokens"),
            ("cost.usd", "gen_ai.usage.cost"),
        ):
            if source in record.attributes:
                attrs.setdefault(convention, record.attributes[source])

    start_ns = str(int(record.start_time * 1_000_000_000))
    end = record.end_time if record.end_time is not None else record.start_time
    end_ns = str(int(end * 1_000_000_000))

    return {
        "traceId": _otlp_trace_id(record.trace_id),
        "spanId": _otlp_span_id(record.span_id),
        "name": record.name,
        "kind": 3 if is_llm else 1,  # CLIENT for llm calls, INTERNAL else
        "startTimeUnixNano": start_ns,
        "endTimeUnixNano": end_ns,
        "attributes": [
            {"key": key, "value": _attr_value(value)} for key, value in attrs.items()
        ],
        "status": {"code": _status_code(record.status)},
    }


def _get_service_version() -> str:
    """Package version for the OTLP resource (cached, never raises)."""
    global _service_version
    if _service_version is None:
        try:
            from importlib.metadata import PackageNotFoundError, version

            try:
                _service_version = version("orya-agent")
            except PackageNotFoundError:
                _service_version = "7.0.0"
        except Exception:  # pragma: no cover - defensive
            _service_version = "7.0.0"
    return _service_version


def build_otlp_payload(records: list[SpanRecord]) -> dict[str, Any]:
    """Batch of records → OTLP ``TracesData`` JSON (``resourceSpans``)."""
    version = _get_service_version()
    return {
        "resourceSpans": [
            {
                "resource": {
                    "attributes": [
                        {
                            "key": "service.name",
                            "value": {"stringValue": "orya-agent"},
                        },
                        {
                            "key": "service.version",
                            "value": {"stringValue": version},
                        },
                    ]
                },
                "scopeSpans": [
                    {
                        "scope": {
                            "name": "app.core.observability",
                            "version": version,
                        },
                        "spans": [span_to_otlp(record) for record in records],
                    }
                ],
            }
        ]
    }


# --- Config resolution ----------------------------------------------------


def _is_configured(settings: Any) -> bool:
    """Effective enablement: kill-switch AND host AND both keys (A-15)."""
    if not settings.langfuse_export_enabled:
        return False
    if not (settings.langfuse_host or "").strip():
        return False
    public = settings.langfuse_public_key
    secret = settings.langfuse_secret_key
    if public is None or secret is None:
        return False
    return bool(public.get_secret_value().strip()) and bool(
        secret.get_secret_value().strip()
    )


def resolve_traces_url(settings: Any) -> str | None:
    """Full OTLP traces URL, or ``None`` when nothing is configured.

    ``OTEL_EXPORTER_OTLP_ENDPOINT`` (generic collector) wins over
    ``LANGFUSE_HOST`` (Langfuse/sampler-proxy base).
    """
    collector = (settings.otel_exporter_otlp_endpoint or "").strip().rstrip("/")
    if collector:
        return f"{collector}{OTLP_PATH_COLLECTOR}"
    host = (settings.langfuse_host or "").strip().rstrip("/")
    if host:
        return f"{host}{OTLP_PATH_LANGFUSE}"
    return None


def _resolve_direct_url(settings: Any) -> str | None:
    """Fail-open fallback URL, or ``None`` (A-15 ``LANGFUSE_DIRECT_URL``)."""
    direct = (settings.langfuse_direct_url or "").strip().rstrip("/")
    if not direct:
        return None
    return f"{direct}{OTLP_PATH_LANGFUSE}"


# --- Exporter -------------------------------------------------------------


class LangfuseOtlpExporter:
    """Queued OTLP/HTTP JSON exporter with retry, cooldown and fail-open.

    The emit path only calls :meth:`offer` (non-blocking, drop-on-full);
    a daemon worker thread drains the queue and POSTs batches. ``post``
    is injectable for tests: ``(url, headers, body) -> None`` raising
    ``_RetryableError``/``_PermanentError`` on failure.
    """

    def __init__(
        self,
        url: str,
        auth: str | None,
        *,
        direct_url: str | None = None,
        post: Any = None,
        backoff_base_s: float = BACKOFF_BASE_S,
        queue_max: int = QUEUE_MAX,
    ) -> None:
        self._url = url
        self._direct_url = (
            direct_url if direct_url is None or direct_url != url else None
        )
        self._headers = {"Content-Type": "application/json"}
        if auth:
            self._headers["Authorization"] = f"Basic {auth}"
        self._queue: queue.Queue[SpanRecord] = queue.Queue(maxsize=queue_max)
        self._post = post if post is not None else self._post_httpx
        self._backoff_base_s = backoff_base_s
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._client: httpx.Client | None = None
        self._consecutive_failures = 0
        self._cooldown_until = 0.0

    # --- emit path (agent-loop safe) ---

    def offer(self, record: SpanRecord) -> None:
        """Enqueue a finished span; drop-on-full, never raises."""
        try:
            self._queue.put_nowait(record)
        except queue.Full:
            _bump(failed=1)
            logger.debug("langfuse export queue full; dropping span %s", record.span_id)

    @property
    def queued(self) -> int:
        return self._queue.qsize()

    # --- worker ---

    def start(self) -> None:
        """Start the background drain thread (idempotent)."""
        if self._thread is not None:
            return
        self._thread = threading.Thread(
            target=self._run, name="orya-langfuse-export", daemon=True
        )
        self._thread.start()

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                first = self._queue.get(timeout=WORKER_POLL_S)
            except queue.Empty:
                continue
            batch = [first]
            while len(batch) < BATCH_MAX:
                try:
                    batch.append(self._queue.get_nowait())
                except queue.Empty:
                    break
            try:
                self.send_batch(batch)
            except Exception:  # noqa: BLE001 - the worker must never die
                _bump(failed=len(batch))
                logger.warning(
                    "langfuse exporter batch failed unexpectedly",
                    exc_info=True,
                )

    # --- delivery ---

    def send_batch(self, records: list[SpanRecord]) -> None:
        """POST one batch with retry, cooldown and direct fail-open.

        Never raises; every outcome is reflected in the export counters.
        """
        if not records:
            return
        if time.monotonic() < self._cooldown_until:
            _bump(failed=len(records))
            logger.debug(
                "langfuse exporter cooling down; dropping %d spans",
                len(records),
            )
            return
        body = json.dumps(build_otlp_payload(records), default=str).encode()
        for attempt in range(1, MAX_ATTEMPTS + 1):
            try:
                self._post(self._url, self._headers, body)
                self._consecutive_failures = 0
                _bump(exported=len(records))
                return
            except _PermanentError as exc:
                logger.error(
                    "langfuse export rejected (%s); dropping %d spans",
                    exc,
                    len(records),
                )
                self._register_failure(len(records))
                return
            except Exception as exc:  # noqa: BLE001 - includes _RetryableError
                if attempt < MAX_ATTEMPTS:
                    time.sleep(self._backoff_base_s * attempt)
                    continue
                if self._direct_url:
                    try:
                        self._post(self._direct_url, self._headers, body)
                        self._consecutive_failures = 0
                        _bump(exported=len(records))
                        return
                    except Exception as direct_exc:  # noqa: BLE001
                        logger.debug("langfuse direct fallback failed: %s", direct_exc)
                logger.warning(
                    "langfuse export failed after %d attempts (%s); dropping %d spans",
                    attempt,
                    exc,
                    len(records),
                )
                self._register_failure(len(records))
                return

    def _post_httpx(self, url: str, headers: dict[str, str], body: bytes) -> None:
        """POST via a reused ``httpx.Client``; raise typed errors."""
        if self._client is None:
            self._client = httpx.Client(timeout=REQUEST_TIMEOUT_S)
        try:
            response = self._client.post(url, content=body, headers=headers)
        except httpx.TransportError as exc:
            raise _RetryableError(str(exc)) from exc
        if 200 <= response.status_code < 300:
            return
        if response.status_code == 429 or response.status_code >= 500:
            raise _RetryableError(f"HTTP {response.status_code}")
        raise _PermanentError(f"HTTP {response.status_code}: {response.text[:200]}")

    def _register_failure(self, count: int) -> None:
        """Count the loss and arm the cooldown after repeated failures."""
        _bump(failed=count)
        self._consecutive_failures += 1
        if self._consecutive_failures >= COOLDOWN_AFTER_FAILURES:
            self._consecutive_failures = 0
            self._cooldown_until = time.monotonic() + COOLDOWN_S

    def flush(self, timeout: float = 2.0) -> None:
        """Best-effort drain of everything queued right now; never raises."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            batch = self._drain()
            if not batch:
                return
            try:
                self.send_batch(batch)
            except Exception:  # noqa: BLE001 - flush must never raise
                _bump(failed=len(batch))
                logger.warning("langfuse flush failed", exc_info=True)

    def _drain(self) -> list[SpanRecord]:
        batch: list[SpanRecord] = []
        while len(batch) < BATCH_MAX:
            try:
                batch.append(self._queue.get_nowait())
            except queue.Empty:
                break
        return batch

    def stop(self, timeout: float = 2.0) -> None:
        """Stop the worker and close the HTTP client; never raises."""
        self._stop.set()
        thread, self._thread = self._thread, None
        if thread is not None:
            thread.join(timeout)
        client, self._client = self._client, None
        if client is not None:
            try:
                client.close()
            except Exception:  # noqa: BLE001 - defensive
                logger.debug("langfuse client close failed", exc_info=True)


# --- Module singleton -----------------------------------------------------

_exporter: LangfuseOtlpExporter | None = None
_init_lock = threading.Lock()


def get_exporter() -> LangfuseOtlpExporter | None:
    """The process-wide exporter when configured, else ``None`` (lazy build)."""
    global _exporter
    settings = get_settings()
    if not _is_configured(settings):
        return None
    with _init_lock:
        if _exporter is None:
            url = resolve_traces_url(settings)
            if url is None:
                return None
            public = settings.langfuse_public_key
            secret = settings.langfuse_secret_key
            auth = base64.b64encode(
                f"{public.get_secret_value()}:{secret.get_secret_value()}".encode()
            ).decode()
            _exporter = LangfuseOtlpExporter(
                url, auth, direct_url=_resolve_direct_url(settings)
            )
        return _exporter


def export_span(record: SpanRecord) -> None:
    """Offer a finished span to the Langfuse exporter; never raises (A-15)."""
    try:
        exporter = get_exporter()
        if exporter is None:
            return
        exporter.offer(record)
    except (
        Exception
    ):  # pragma: no cover - defensive: observability never breaks the agent
        logger.debug("langfuse export offer failed", exc_info=True)


def init_exporter() -> None:
    """Lifespan startup: build and start the worker when configured (A-15)."""
    exporter = get_exporter()
    if exporter is not None:
        exporter.start()


def shutdown_exporter(timeout: float = 2.0) -> None:
    """Lifespan shutdown: flush the queue best-effort, then stop (A-15)."""
    global _exporter
    with _init_lock:
        exporter, _exporter = _exporter, None
    if exporter is None:
        return
    try:
        exporter.flush(timeout=timeout)
    finally:
        exporter.stop(timeout)


def reset_exporter() -> None:
    """Drop the singleton without flushing (tests)."""
    global _exporter
    with _init_lock:
        exporter, _exporter = _exporter, None
    if exporter is not None:
        exporter.stop(timeout=0.0)


# --- Counters -------------------------------------------------------------


def _bump(*, exported: int = 0, failed: int = 0) -> None:
    global _exported_spans_total, _export_errors_total
    with _stats_lock:
        _exported_spans_total += exported
        _export_errors_total += failed


def get_export_stats() -> dict[str, Any]:
    """Exporter state for ``/health/observability`` and ``/metrics`` (A-15)."""
    with _stats_lock:
        exported = _exported_spans_total
        failed = _export_errors_total
    settings = get_settings()
    return {
        "enabled": _is_configured(settings),
        "queued": _exporter.queued if _exporter is not None else 0,
        "exported_total": exported,
        "failed_total": failed,
    }


def reset_export_stats() -> None:
    """Zero the counters (tests)."""
    global _exported_spans_total, _export_errors_total
    with _stats_lock:
        _exported_spans_total = 0
        _export_errors_total = 0
