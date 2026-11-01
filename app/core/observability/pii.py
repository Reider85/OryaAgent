"""PII masking of span content via agent_obs (A-16).

Thin adapter over ``agent_obs.guardrail.PIIDetector``: detection is 100%
SDK-owned (regex path — email/phone/inn/passport/payment; the ML stage
stays off via the SDK default ``AGENT_OBS_PII_ML_ENABLED=false``); this
module only orchestrates the offset splice (same algorithm as
``FieldMasker._apply_full_mask_to_string``).

Fail-closed contract (mirrors ``agent_obs.observability``):
- detector package unavailable -> ``[REDACTED:guardrail_unavailable]``
- detector raised -> ``[REDACTED:guardrail_error]``
- ``settings.agent_obs_guardrail_enabled=false`` -> text passes through
  (debugging only, documented in .env.example).

Never raises.
"""

from __future__ import annotations

import logging

from app.core.config import get_settings

logger = logging.getLogger(__name__)

#: SDK-identical fail-closed markers (agent_obs/observability.py).
REDACTED_UNAVAILABLE = "[REDACTED:guardrail_unavailable]"
REDACTED_ERROR = "[REDACTED:guardrail_error]"

_detector: object | None = None
_detector_loaded = False


def _get_detector() -> object | None:
    """Cached lazy PIIDetector; ``None`` when agent_obs is not installed."""
    global _detector, _detector_loaded
    if not _detector_loaded:
        try:
            from agent_obs.guardrail.pii_detector import PIIDetector

            _detector = PIIDetector()
        except Exception:  # pragma: no cover - ImportError or detector init fault
            logger.warning("agent_obs PIIDetector unavailable", exc_info=True)
            _detector = None
        _detector_loaded = True
    return _detector


def clear_detector_cache() -> None:
    """Drop the cached detector (tests / env changes)."""
    global _detector, _detector_loaded
    _detector = None
    _detector_loaded = False


def agent_obs_available() -> bool:
    """True when the agent_obs guardrail surface is importable and inited."""
    return _get_detector() is not None


def mask_text(text: str) -> str:
    """Mask PII entities in *text* for span attributes. Never raises."""
    if not text:
        return text
    try:
        settings = get_settings()
        if not settings.agent_obs_guardrail_enabled:
            return text
    except Exception:  # pragma: no cover - settings fault -> fail closed
        return REDACTED_UNAVAILABLE

    detector = _get_detector()
    if detector is None:
        return REDACTED_UNAVAILABLE

    try:
        matches = detector.detect(text)  # type: ignore[attr-defined]
        if not matches:
            return text
        # Sort by span_start descending to avoid index shifts — same
        # algorithm as agent_obs FieldMasker._apply_full_mask_to_string.
        masked = text
        for match in sorted(matches, key=lambda m: m.span_start, reverse=True):
            masked = masked[: match.span_start] + match.mask + masked[match.span_end :]
        return masked
    except Exception:  # pragma: no cover - detector fault -> fail closed
        logger.warning("PII masking failed", exc_info=True)
        return REDACTED_ERROR
