"""Retrieval orchestration tool for LLM."""

from __future__ import annotations

import logging
from typing import Any

from langchain_core.tools import tool

from app.core.observability.spans import timed_span
from app.core.retrieval.models import RetrievedChunk
from app.core.retrieval.orchestrator import get_retrieval_orchestrator

logger = logging.getLogger(__name__)


@tool
async def retrieval_orchestrate(
    session_state: dict[str, Any],
    top_k: int = 5,
) -> list[RetrievedChunk]:
    """Orchestrates retrieval using intelligent strategy selection.

    This tool automatically decides when and how to retrieve information based on:
    - Session context (turn count, previous messages)
    - Heuristics (referential markers, similarity, intent detection)
    - Available strategies (none, standard, topic_continuation, speculative_prefetch, explicit_recall, code_lookup, degraded)

    Args:
        session_state: Current session state including turn_count, last_message, previous_messages
        top_k: Maximum number of results to return (default: 5)

    Returns:
        List of RetrievedChunk objects with content, source, score, and metadata
    """
    with timed_span(
        span_type="tool.retrieval_orchestrate",
        name="tool.retrieval_orchestrate",
        attributes={"top_k": top_k},
    ):
        orchestrator = get_retrieval_orchestrator()

        try:
            results = await orchestrator.orchestrate(
                session_state=session_state,
                top_k=top_k,
            )

            logger.info(f"Retrieval orchestration returned {len(results)} results")
            return results

        except Exception as e:
            logger.error(f"Retrieval orchestration failed: {e}")
            return []
