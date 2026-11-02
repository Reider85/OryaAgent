"""ConnectionPool (A-20) — per-provider keepalive httpx clients for the LLM seam.

``get_llm()`` hands the constructed chat model a pooled async client —
``httpx.AsyncClient`` for everything except the anthropic SDK (1.15+
speaks the vendored ``httpx2`` fork and hard-rejects httpx objects, so
that flavor is pooled as ``httpx2.AsyncClient``) — built with
``retries=2`` and ``Limits(keepalive_expiry=60, ...)``. TCP+TLS is paid
once per provider instead of on every turn (−200..500 ms cold-start,
PROMPT_ALPHA §6, ADR-0014).

Design (see ``.opencode/plans/A-20-connection-pool.md`` for the spec
reconciliation):

- Per-provider ``OrderedDict`` (LRU order) guarded by a ``threading.Lock``
  — the factory seam is synchronous, so pool mutations cannot use an
  ``asyncio.Lock``; the async health-check takes the same lock in short
  critical sections (no await while held).
- ``acquire`` reuses the most-recently-used healthy client (a "hit",
  ``pool_hit=true``, ~0 ms); ``exclusive=True`` always spawns a dedicated
  client (streaming / parallel turns, ADR-0014) and, when the pool is
  over ``max_size``, evicts (closes) the least-recently-used entry.
  Fail-open: any pool error returns a plain untracked client — the
  agent-loop is never blocked or failed by the pool.
- Loop-affinity guard (same precedent as the A-11 asyncpg pool): an entry
  recorded on a different event loop is dropped instead of reused.
- Periodic health-check (``pool_health_worker``, FastAPI lifespan,
  ``LLM_POOL_HEALTH_INTERVAL``, 0 = off): HEAD via the pooled client when
  the provider declares ``health_path``, otherwise a TCP(+TLS) connect
  probe; unhealthy entries are closed and removed — the next ``acquire``
  spawns a replacement.
- Observability: ``tcp.pool_hit`` / ``tcp.connect_duration_ms`` are staged
  in a ContextVar at acquire time and stamped by ``TracedChatModel`` onto
  every ``llm.call`` span of the turn; ``orya_llm_pool_size`` /
  ``orya_llm_pool_hit_rate`` / ``orya_llm_pool_unhealthy_total`` are
  rendered from :func:`get_pool_stats` by ``app/api/metrics.py``.
"""

from __future__ import annotations

import asyncio
import logging
import ssl
import threading
import time
import uuid
from collections import OrderedDict
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlparse

import httpx

try:  # anthropic>=1.15 vendors its own httpx fork and rejects httpx objects
    import httpx2
except ImportError:  # pragma: no cover - anthropic always pulls httpx2 in
    httpx2 = None  # type: ignore[assignment]

from app.core.config import get_settings

logger = logging.getLogger(__name__)

#: httpx transport knobs from the A-20 constraints block.
POOL_TRANSPORT_RETRIES = 2
POOL_KEEPALIVE_EXPIRY = 60.0
#: Health probes (HEAD / TCP) time out fast — they must never stall a pass.
PROBE_TIMEOUT_S = 5.0
#: Client "flavors": the anthropic SDK (httpx2) refuses ``httpx`` objects,
#: everything else speaks plain httpx (google-genai accepts both).
CLIENT_FLAVORS = ("httpx", "httpx2")

# ---------------------------------------------------------------------------
# tcp.* span-attribute staging (consumed by TracedChatModel, A-20)
# ---------------------------------------------------------------------------

#: Per-provider ``(pool_hit, connect_duration_ms)`` staged by ``acquire``
#: during ``get_llm()``; read (not cleared) by the tracing wrapper for every
#: ``llm.call`` of that provider in the same task context.
_tcp_attrs: ContextVar[dict[str, tuple[bool, float]] | None] = ContextVar(
    "orya_pool_tcp_attrs", default=None
)


def stage_tcp_attrs(
    provider: str, *, pool_hit: bool, connect_duration_ms: float
) -> None:
    """Stage ``tcp.*`` values for the next ``llm.call`` spans (A-20)."""
    merged = dict(_tcp_attrs.get() or {})
    merged[provider] = (pool_hit, connect_duration_ms)
    _tcp_attrs.set(merged)


def peek_tcp_attrs(provider: str) -> tuple[bool, float] | None:
    """Read the staged ``tcp.*`` values for *provider* (never clears)."""
    staged = _tcp_attrs.get()
    if not staged:
        return None
    return staged.get(provider)


def clear_tcp_attrs() -> None:
    """Drop all staged ``tcp.*`` values (tests)."""
    _tcp_attrs.set(None)


# ---------------------------------------------------------------------------
# Pool
# ---------------------------------------------------------------------------


@dataclass
class PooledConnection:
    """One keepalive client slot of a provider's hot pool."""

    id: str
    provider: str
    client: Any
    #: Which client package this entry speaks (``httpx`` | ``httpx2``).
    flavor: str = "httpx"
    base_url: str = ""
    health_url: str | None = None
    #: Event loop this entry was acquired on (None = acquired synchronously).
    loop: asyncio.AbstractEventLoop | None = None
    created_at: float = field(default_factory=time.time)
    last_used: float = field(default_factory=time.time)
    #: Latency of the last successful health probe, if one ran yet.
    last_probe_ms: float | None = None


@dataclass(frozen=True)
class AcquireResult:
    """What ``acquire`` hands back to the factory."""

    client: Any
    provider: str
    pool_hit: bool
    connect_duration_ms: float


def _close_best_effort(client: Any) -> None:
    """Close a pooled client without ever raising into the caller.

    httpx/httpx 0.28 expose only the async ``aclose``: with a running loop
    the close is scheduled as a task, without one the client is dropped
    (its sockets belong to a loop that is already gone — the A-11 pool
    drops loop-bound singletons the same way).
    """
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        logger.debug("pooled client dropped without close (no running loop)")
        return

    async def _close() -> None:
        try:
            await client.aclose()
        except Exception:  # noqa: BLE001 - best-effort teardown
            logger.debug("pool aclose failed", exc_info=True)

    loop.create_task(_close())


class ConnectionPool:
    """LRU pool of keepalive ``httpx.AsyncClient`` instances per provider."""

    def __init__(
        self,
        *,
        enabled: bool = True,
        max_size: int = 4,
        keepalive_expiry: float = POOL_KEEPALIVE_EXPIRY,
        retries: int = POOL_TRANSPORT_RETRIES,
    ) -> None:
        self.enabled = enabled
        self.max_size = max(1, int(max_size))
        self.keepalive_expiry = keepalive_expiry
        self.retries = retries
        self._lock = threading.Lock()
        self._pools: dict[str, OrderedDict[str, PooledConnection]] = {}
        self._hits: dict[str, int] = {}
        self._misses: dict[str, int] = {}
        self._unhealthy: dict[str, int] = {}
        self._evicted: dict[str, int] = {}

    # -- internals ---------------------------------------------------------

    def _new_client(self, flavor: str = "httpx") -> Any:
        # httpx 0.28 has no ``keepalive_expiry`` on the transport itself
        # (the A-20 constraint block predates that API): the knob lives in
        # ``Limits`` — ``max_keepalive_connections`` is the per-provider
        # hot-connection count of the spec, ``keepalive_expiry=60`` its TTL.
        if flavor == "httpx2":
            if httpx2 is None:
                raise RuntimeError("httpx2 is unavailable (anthropic not installed)")
            mod: Any = httpx2
        else:
            mod = httpx
        return mod.AsyncClient(
            transport=mod.AsyncHTTPTransport(
                retries=self.retries,
                limits=mod.Limits(
                    max_connections=100,
                    max_keepalive_connections=self.max_size,
                    keepalive_expiry=self.keepalive_expiry,
                ),
            )
        )

    def _drop_locked(
        self, provider: str, entry: PooledConnection, *, unhealthy: bool
    ) -> None:
        """Remove *entry* from its LRU and close it (``self._lock`` held)."""
        pool = self._pools.get(provider)
        if pool is not None:
            pool.pop(entry.id, None)
            if not pool:
                self._pools.pop(provider, None)
        if unhealthy:
            self._unhealthy[provider] = self._unhealthy.get(provider, 0) + 1
        _close_best_effort(entry.client)

    def _current_loop(self) -> asyncio.AbstractEventLoop | None:
        try:
            return asyncio.get_running_loop()
        except RuntimeError:
            return None

    # -- acquire -----------------------------------------------------------

    def acquire(
        self,
        provider: str,
        *,
        base_url: str = "",
        health_url: str | None = None,
        exclusive: bool = False,
        flavor: str = "httpx",
    ) -> AcquireResult:
        """Return a pooled client for *provider* (sync, never raises).

        Reuses the most-recently-used healthy entry unless ``exclusive``
        requests a dedicated connection; entries recorded on another event
        loop are dropped (A-11 loop-guard precedent) and clients beyond
        ``max_size`` are evicted LRU-first. ``flavor`` picks the client
        package (``httpx2`` for the anthropic SDK, which rejects httpx).
        """
        started = time.perf_counter()

        def _elapsed_ms() -> float:
            return round((time.perf_counter() - started) * 1000, 3)

        if not self.enabled:
            # Kill-switch: stock behaviour — a fresh, untracked client.
            return AcquireResult(
                self._new_client(flavor), provider, False, _elapsed_ms()
            )

        try:
            running = self._current_loop()
            with self._lock:
                pool = self._pools.setdefault(provider, OrderedDict())

                # Drop loop-affine stragglers first (they cannot be reused).
                for cid in list(pool):
                    entry = pool[cid]
                    if entry.loop is not None and running is not None:
                        if entry.loop is not running:
                            self._drop_locked(provider, entry, unhealthy=False)
                            continue

                if not exclusive and pool:
                    # LRU hit: most-recently-used healthy entry.
                    entry = next(reversed(pool.values()))
                    pool.move_to_end(entry.id)
                    entry.last_used = time.time()
                    if entry.loop is None and running is not None:
                        entry.loop = running
                    self._hits[provider] = self._hits.get(provider, 0) + 1
                    return AcquireResult(entry.client, provider, True, _elapsed_ms())

                # Miss: spawn a new connection (wait-free, never blocks).
                entry = PooledConnection(
                    id=uuid.uuid4().hex,
                    provider=provider,
                    client=self._new_client(flavor),
                    flavor=flavor,
                    base_url=base_url,
                    health_url=health_url,
                    loop=running,
                )
                pool[entry.id] = entry
                self._misses[provider] = self._misses.get(provider, 0) + 1

                # LRU eviction beyond max_size (spec: over limit → spawn
                # new, then evict the oldest — never wait for a slot).
                while len(pool) > self.max_size:
                    _, oldest = pool.popitem(last=False)
                    self._evicted[provider] = self._evicted.get(provider, 0) + 1
                    _close_best_effort(oldest.client)

                return AcquireResult(entry.client, provider, False, _elapsed_ms())
        except Exception:  # noqa: BLE001 - fail-open: pool must not break the seam
            logger.warning("connection pool acquire failed", exc_info=True)
            # Do not leave an empty provider bucket behind (stats stay clean).
            with self._lock:
                bucket = self._pools.get(provider)
                if bucket is not None and not bucket:
                    self._pools.pop(provider, None)
            try:
                client = self._new_client(flavor)
            except Exception:  # noqa: BLE001 - last resort, plain httpx
                client = httpx.AsyncClient()
            return AcquireResult(client, provider, False, _elapsed_ms())

    # -- health ------------------------------------------------------------

    async def _probe(self, entry: PooledConnection) -> tuple[bool, float]:
        """One health probe — overridable in tests. Returns (ok, latency_ms)."""
        started = time.perf_counter()

        def _ms() -> float:
            return round((time.perf_counter() - started) * 1000, 1)

        if entry.health_url:
            try:
                resp = await entry.client.head(
                    entry.health_url, timeout=PROBE_TIMEOUT_S
                )
                # Any answer < 500 means the endpoint is alive (405/401
                # are fine — the server responded).
                return resp.status_code < 500, _ms()
            except httpx.HTTPError:
                return False, _ms()

        parsed = urlparse(entry.base_url or "")
        host = parsed.hostname
        if not host:
            return False, _ms()
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        writer: asyncio.StreamWriter | None = None
        try:
            ssl_ctx = ssl.create_default_context() if parsed.scheme == "https" else None
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(
                    host,
                    port,
                    ssl=ssl_ctx,
                    server_hostname=host if ssl_ctx else None,
                ),
                timeout=PROBE_TIMEOUT_S,
            )
            del reader
            return True, _ms()
        except (TimeoutError, OSError, ssl.SSLError):
            return False, _ms()
        finally:
            if writer is not None:
                try:
                    writer.close()
                    await writer.wait_closed()
                except Exception:  # noqa: BLE001 - probe teardown
                    pass

    async def health_check(self) -> dict[str, Any]:
        """Probe every pooled entry; drop the unhealthy ones (fail-open)."""
        with self._lock:
            snapshot = [
                (provider, entry)
                for provider, pool in self._pools.items()
                for entry in list(pool.values())
            ]

        unhealthy: list[str] = []
        checked = 0
        for provider, entry in snapshot:
            checked += 1
            try:
                ok, latency = await self._probe(entry)
            except Exception:  # noqa: BLE001 - probe errors = unhealthy
                ok, latency = False, 0.0
            with self._lock:
                entry.last_probe_ms = latency
                still_pooled = (
                    self._pools.get(provider) is not None
                    and entry.id in self._pools[provider]
                )
                if still_pooled and not ok:
                    self._drop_locked(provider, entry, unhealthy=True)
                    unhealthy.append(f"{provider}:{entry.id[:8]}")
        return {"checked": checked, "unhealthy": unhealthy}

    # -- introspection -----------------------------------------------------

    def stats(self) -> dict[str, dict[str, Any]]:
        """Per-provider counters for ``/metrics`` and tests."""
        with self._lock:
            providers = set(self._pools) | set(self._hits) | set(self._misses)
            providers |= set(self._unhealthy)
            out: dict[str, dict[str, Any]] = {}
            for provider in sorted(providers):
                hits = self._hits.get(provider, 0)
                misses = self._misses.get(provider, 0)
                total = hits + misses
                out[provider] = {
                    "size": len(self._pools.get(provider, {})),
                    "hits": hits,
                    "misses": misses,
                    "hit_rate": (hits / total) if total else 0.0,
                    "unhealthy_total": self._unhealthy.get(provider, 0),
                    "evicted_total": self._evicted.get(provider, 0),
                    "max_size": self.max_size,
                }
            return out

    async def aclose(self) -> None:
        """Close every pooled client (lifespan shutdown). Never raises."""
        with self._lock:
            entries = [
                entry for pool in self._pools.values() for entry in list(pool.values())
            ]
            self._pools.clear()
        for entry in entries:
            try:
                await entry.client.aclose()
            except Exception:  # noqa: BLE001 - teardown must not raise
                logger.debug("pool aclose failed", exc_info=True)

    def reset(self) -> None:
        """Drop all state without awaiting (tests / loop changes)."""
        with self._lock:
            entries = [
                entry for pool in self._pools.values() for entry in list(pool.values())
            ]
            self._pools.clear()
            self._hits.clear()
            self._misses.clear()
            self._unhealthy.clear()
            self._evicted.clear()
        for entry in entries:
            _close_best_effort(entry.client)


# ---------------------------------------------------------------------------
# Module-level singleton + lifespan worker
# ---------------------------------------------------------------------------

_pool: ConnectionPool | None = None
_pool_singleton_lock = threading.Lock()


def get_connection_pool() -> ConnectionPool:
    """The process-wide pool, built from the A-20 settings on first use."""
    global _pool
    with _pool_singleton_lock:
        if _pool is None:
            settings = get_settings()
            _pool = ConnectionPool(
                enabled=settings.llm_pool_enabled,
                max_size=settings.llm_pool_size,
            )
        return _pool


def reset_connection_pool() -> None:
    """Close and drop the singleton (tests, loop changes). Never raises."""
    global _pool
    with _pool_singleton_lock:
        old, _pool = _pool, None
    if old is not None:
        old.reset()


def get_pool_stats() -> dict[str, dict[str, Any]]:
    """Per-provider counters of the process-wide pool (for ``/metrics``)."""
    return get_connection_pool().stats()


async def pool_health_worker(interval: float) -> None:
    """Periodic health-check loop (A-20) — started by the FastAPI lifespan.

    Sleeps first (the first pass runs ``interval`` seconds after startup),
    never lets a failed pass kill the loop, and exits on cancellation.
    """
    if interval <= 0:
        return
    pool = get_connection_pool()
    while True:
        await asyncio.sleep(interval)
        try:
            summary = await pool.health_check()
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 - worker must survive anything
            logger.warning("connection pool health pass failed", exc_info=True)
            continue
        if summary["unhealthy"]:
            logger.info(
                "connection pool dropped unhealthy entries: %s",
                ", ".join(summary["unhealthy"]),
            )
