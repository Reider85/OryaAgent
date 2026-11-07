"""Memory-extractor LLM-worker for batch fact extraction (B-22).

Extracts facts from memory using batch LLM processing after N messages.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from datetime import datetime
from typing import Any, Dict, List, Optional

from app.core.memory.sqlitestore import get_sqlite_store
from app.core.observability.metrics import MemoryExtractionMetricsContext
from app.core.observability.spans import emit_span
from app.core.memory.md_store import get_md_store
from app.tools._validators import validate_path

logger = logging.getLogger(__name__)


class MemoryExtractor:
    """LLM-based memory extractor for fact generation."""

    def __init__(self, model_name: str = "haiku", batch_size: int = 10, extraction_interval: int = 10):
        self.model_name = model_name
        self.batch_size = batch_size
        self.extraction_interval = extraction_interval
        self._sqlite_store = None
        self._md_store = None
        self._extracting = False
        self._last_extraction_time: Dict[str, float] = {}

    async def initialize(self) -> None:
        """Initialize the extractor with required stores."""
        self._sqlite_store = await get_sqlite_store()
        self._md_store = get_md_store()

    async def should_extract(self, session_id: str) -> bool:
        """Check if extraction should be performed for a session."""
        if self._extracting:
            return False

        # Check time since last extraction
        last_time = self._last_extraction_time.get(session_id, 0)
        time_since_last = time.time() - last_time
        if time_since_last < self.extraction_interval * 60:  # Convert to seconds
            return False

        # Get message count
        messages_file = self._md_store.get_session_memory_dir(session_id) / "LEARNED.md"
        if not messages_file.exists():
            return False

        message_count = len(messages_file.read_text(encoding="utf-8").split("\n"))
        return message_count >= self.batch_size

    async def extract_facts(self, session_id: str) -> List[Dict[str, Any]]:
        """Extract facts from session messages using LLM."""
        if not self._sqlite_store or not self._md_store:
            await self.initialize()

        self._extracting = True
        self._last_extraction_time[session_id] = time.time()

        try:
            with MemoryExtractionMetricsContext(session_id) as metrics_context:
                # Get messages from LEARNED.md
                messages_file = self._md_store.get_session_memory_dir(session_id) / "LEARNED.md"
                if not messages_file.exists():
                    return []

                messages_content = messages_file.read_text(encoding="utf-8")
                if not messages_content.strip():
                    return []

                # Get recent messages (last batch_size)
                messages = messages_content.split("\n")[-self.batch_size:]
                
                # Extract facts using LLM
                facts = await self._extract_with_llm(session_id, messages)
                
                # Store facts
                await self._store_facts(session_id, facts)
                
                # Update metrics
                metrics_context.facts_count = len(facts)
                metrics_context.source_messages = len(messages)
                
                logger.info(f"Extracted {len(facts)} facts from {len(messages)} messages for session {session_id}")
                return facts

        except Exception as e:
            logger.error(f"Failed to extract facts for session {session_id}: {e}")
            return []
        finally:
            self._extracting = False

    async def _extract_with_llm(self, session_id: str, messages: List[str]) -> List[Dict[str, Any]]:
        """Extract facts using LLM."""
        # This is a placeholder implementation
        # In a real implementation, this would call an LLM with a prompt
        # to extract structured facts from the messages
        
        facts = []
        
        for i, message in enumerate(messages):
            if not message.strip():
                continue
                
            # Simple fact extraction (in real implementation, use LLM)
            fact = {
                "id": f"fact_{int(time.time() * 1000)}_{i}",
                "session_id": session_id,
                "content": message,
                "type": "message_summary",
                "extracted_at": datetime.utcnow().isoformat(),
                "confidence": 0.8,
                "source_message_index": i,
            }
            
            facts.append(fact)
        
        return facts

    async def _store_facts(self, session_id: str, facts: List[Dict[str, Any]]) -> None:
        """Store extracted facts in the SQLite store."""
        for fact in facts:
            try:
                await self._sqlite_store.add_memory(
                    session_id,
                    json.dumps(fact, ensure_ascii=False),
                    {"type": "extracted_fact", "fact_id": fact["id"]},
                    expires_in_hours=24 * 7,  # Facts expire after 1 week
                )
            except Exception as e:
                logger.error(f"Failed to store fact {fact.get('id', 'unknown')}: {e}")

    async def get_extracted_facts(self, session_id: str, limit: int = 50) -> List[Dict[str, Any]]:
        """Get extracted facts for a session."""
        if not self._sqlite_store:
            await self.initialize()

        # Search for facts
        facts_data = await self._sqlite_store.search_memories(
            session_id,
            '"extracted_fact"',
            limit=limit,
        )
        
        return facts_data

    async def get_extraction_stats(self, session_id: str) -> Dict[str, Any]:
        """Get extraction statistics for a session."""
        if not self._sqlite_store:
            await self.initialize()

        # Get total facts count
        facts_data = await self._sqlite_store.search_memories(
            session_id,
            '"extracted_fact"',
            limit=1000,
        )
        
        total_facts = len(facts_data)
        
        # Get oldest and newest extraction
        if facts_data:
            oldest = min(facts_data, key=lambda x: x["created_at"])
            newest = max(facts_data, key=lambda x: x["created_at"])
        else:
            oldest = None
            newest = None
        
        return {
            "session_id": session_id,
            "total_facts": total_facts,
            "olthest_extraction": oldest["created_at"] if oldest else None,
            "newest_extraction": newest["created_at"] if newest else None,
            "last_extraction_time": self._last_extraction_time.get(session_id, 0),
        }


# Global instance
_memory_extractor = None


async def get_memory_extractor() -> MemoryExtractor:
    """Get the global memory extractor instance."""
    global _memory_extractor
    if _memory_extractor is None:
        _memory_extractor = MemoryExtractor()
        await _memory_extractor.initialize()
    return _memory_extractor


async def initialize_memory_extractor(
    model_name: str = "haiku",
    batch_size: int = 10,
    extraction_interval: int = 10,
) -> MemoryExtractor:
    """Initialize the memory extractor with custom parameters."""
    global _memory_extractor
    _memory_extractor = MemoryExtractor(
        model_name=model_name,
        batch_size=batch_size,
        extraction_interval=extraction_interval,
    )
    await _memory_extractor.initialize()
    return _memory_extractor


async def extract_facts_for_session(session_id: str) -> List[Dict[str, Any]]:
    """Extract facts for a specific session."""
    extractor = await get_memory_extractor()
    return await extractor.extract_facts(session_id)