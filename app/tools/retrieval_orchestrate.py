"""Retrieval orchestration tool for LLM."""

from __future__ import annotations

import logging
from typing import Any, Dict, List

from app.core.retrieval.orchestrator import get_retrieval_orchestrator
from app.core.retrieval.models import RetrievedChunk
from app.core.observability.spans import emit_span
from app.core.tools._validators import validate_path

logger = logging.getLogger(__name__)


@tool
async def retrieval_orchestrate(
    """
    Orchestrates retrieval using intelligent strategy selection.
    
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
    session_state: Dict[str, Any] = validate_path("session_state", "session_state")
    top_k: int = validate_path("top_k", "top_k", default=5)
    
    with emit_span("tool.retrieval_orchestrate", {"top_k": top_k}):
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