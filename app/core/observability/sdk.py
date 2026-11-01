"""OryaObservability SDK integration (A-16, bridge architecture).

Composition root for the A-16 pieces that ride on OryaAgent's own span
seam (:mod:`app.core.observability.spans`) instead of the SDK pipeline:
the SDK's ULID ids are incompatible with our W3C-hex cross-link (A-06)
and A-15 already owns the OTLP/Langfuse export. What we take from
``agent_obs``: PIIDetector masking (:mod:`app.core.observability.pii`)
and the SpanType/attribute conventions.

Provides:
- ``OryaObservability`` — wrapper: ``instrument_graph`` registrar +
  ``emit_memory_write`` span helper.
- ``get_observability()`` — cached singleton.
- ``init_observability_sdk()`` — lifespan probe (logs SDK availability).

The agent-obs package is an OPT-IN install (``uv pip install -e
../OryaObservability``); without it everything here still works — content
attributes fail-closed via :mod:`app.core.observability.pii`.
"""

from __future__ import annotations

import logging

from app.core.config import get_settings
from app.core.observability.pii import agent_obs_available
from app.core.observability.spans import emit_span

logger = logging.getLogger(__name__)

#: Span identity for agent.loop / resource attributes (A-16).
#: Version mirrors the FastAPI app version (app/main.py).
AGENT_ID = "orya-agent"
AGENT_VERSION = "7.0.0"


class OryaObservability:
    """A-16 wrapper over the OryaObservability integration points."""

    def __init__(self) -> None:
        self._sdk_available: bool | None = None

    @property
    def enabled(self) -> bool:
        """Master kill-switch for A-16 span emission (settings)."""
        try:
            return get_settings().agent_obs_enabled
        except Exception:  # pragma: no cover - settings fault -> fail closed
            return False

    @property
    def sdk_available(self) -> bool:
        """True when the agent_obs guardrail surface is importable."""
        if self._sdk_available is None:
            self._sdk_available = agent_obs_available()
        return self._sdk_available

    def instrument_graph(self, graph: object) -> object:
        """A-16 registrar: validate seams and return *graph* unchanged.

        The SDK has no LangGraph instrumentation; emission lives in the
        graph nodes (``tool.call`` in ``tools_node``) and the turn driver
        (``agent.loop`` in ``app.core.agent``), each gated by
        ``settings.agent_obs_enabled``. This method exists for the
        spec-shaped call site and logs the seam state once.
        """
        logger.debug(
            "instrument_graph: enabled=%s sdk_available=%s",
            self.enabled,
            self.sdk_available,
        )
        return graph

    def emit_memory_write(
        self,
        *,
        file: str,
        source: str,
        compacted: bool = False,
        memory_id: str = "",
        status: str = "ok",
    ) -> None:
        """Emit a ``memory.write`` span (A-16). Never raises.

        Args:
            file: L0 memory filename (e.g. "PROJECT.md", "DECISIONS.md").
            source: Writer identity ("learn", "compactor", ...).
            compacted: True when the write is a compaction rewrite.
            memory_id: Optional item id from the caller (learn entries).
        """
        if not self.enabled:
            return
        try:
            emit_span(
                span_type="memory.write",
                name=f"memory.write:{file}",
                attributes={
                    "memory.id": memory_id,
                    "memory.file": file,
                    "memory.source": source,
                    "memory.compacted": "true" if compacted else "false",
                },
                status=status,
            )
        except Exception:  # pragma: no cover - defensive
            logger.warning("memory.write span emission failed", exc_info=True)


_observability: OryaObservability | None = None


def get_observability() -> OryaObservability:
    """The cached OryaObservability wrapper (created on first use)."""
    global _observability
    if _observability is None:
        _observability = OryaObservability()
    return _observability


def init_observability_sdk() -> None:
    """Lifespan probe: create the wrapper and log the seam state.

    Fail-soft: observability must never block startup (same contract as
    ``init_exporter`` in app/core/observability/langfuse.py).
    """
    try:
        obs = get_observability()
        logger.debug(
            "A-16 observability: enabled=%s agent_obs_available=%s",
            obs.enabled,
            obs.sdk_available,
        )
    except Exception:  # pragma: no cover - defensive
        logger.warning("observability sdk init failed", exc_info=True)
