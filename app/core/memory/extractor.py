"""Memory-extractor LLM-worker for batch fact extraction (B-22).

Extracts facts from memory using batch LLM processing after N messages.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from app.core.memory.sqlitestore import get_sqlite_store
from app.core.observability.metrics import MemoryExtractionMetricsContext
from app.core.observability.spans import emit_span
from app.core.memory.md_store import get_md_store
from app.core.memory.prompts import MEMORY_EXTRACTION_PROMPT
from app.core.llm.factory import get_llm
from app.core import config as app_config
from app.tools._validators import validate_path

logger = logging.getLogger(__name__)


class MemoryExtractor:
    """LLM-based memory extractor for fact generation."""

    def __init__(
        self,
        model_name: str = "haiku",
        batch_size: int = 10,
        extraction_interval: int = 10,
    ):
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
                messages_file = (
                    self._md_store.get_session_memory_dir(session_id) / "LEARNED.md"
                )
                if not messages_file.exists():
                    return []

                messages_content = messages_file.read_text(encoding="utf-8")
                if not messages_content.strip():
                    return []

                # Get recent messages (last batch_size)
                messages = messages_content.split("\n")[-self.batch_size :]

                # Extract facts using LLM
                facts = await self._extract_with_llm(session_id, messages)

                # Store facts
                await self._store_facts(session_id, facts)

                # Update metrics
                metrics_context.facts_count = len(facts)
                metrics_context.source_messages = len(messages)

                logger.info(
                    f"Extracted {len(facts)} facts from {len(messages)} messages for session {session_id}"
                )
                return facts

        except Exception as e:
            logger.error(f"Failed to extract facts for session {session_id}: {e}")
            return []
        finally:
            self._extracting = False

    async def _extract_with_llm(
        self, session_id: str, messages: List[str]
    ) -> List[Dict[str, Any]]:
        """Extract facts using LLM."""
        if not messages:
            return []

        try:
            # Get the memory extractor model from settings
            settings = app_config.get_settings()
            extractor_model = settings.llm_memory_extractor_model
            
            logger.debug(f"Extractor model: {extractor_model}")
            
            # Get LLM instance
            try:
                llm = get_llm(provider=extractor_model.split("-")[0], model=extractor_model)
                logger.debug(f"Successfully got LLM for {extractor_model}")
            except Exception as e:
                logger.error(f"Failed to get LLM: {e}")
                raise
            
            # Prepare messages for the prompt
            messages_text = "\n".join(f"- {msg}" for msg in messages if msg.strip())
            logger.debug(f"Messages text: {messages_text}")
            
            # Format the extraction prompt
            try:
                prompt = MEMORY_EXTRACTION_PROMPT.format(messages=messages_text)
                logger.debug(f"Formatted prompt: {prompt[:200]}...")
            except Exception as e:
                logger.error(f"Failed to format prompt: {e}")
                logger.error(f"Messages text: {messages_text}")
                raise
            
            # Create the message for the LLM
            from langchain_core.messages import HumanMessage
            llm_message = HumanMessage(content=prompt)
            
            # Call the LLM
            with emit_span("memory.extract", {"memory.extract.method": "llm_call"}) as span:
                response = await llm.ainvoke([llm_message])
                span.set_attribute("memory.extract.llm_model", extractor_model)
                
                # Parse the response
                response_text = response.content
                extracted_items = self._parse_extraction_response(response_text)
                
                # Process and score the extracted items
                processed_items = []
                for item in extracted_items:
                    processed_item = self._process_extracted_item(item, session_id, len(messages))
                    processed_items.append(processed_item)
                
                return processed_items
                
        except Exception as e:
            logger.error(f"LLM extraction failed for session {session_id}: {e}")
            # Fallback to simple extraction
            return await self._fallback_extraction(session_id, messages)
    
    def _parse_extraction_response(self, response_text: str) -> List[Dict[str, Any]]:
        """Parse the LLM response and extract structured items."""
        try:
            # Try to parse JSON from response
            response_data = json.loads(response_text)
            if isinstance(response_data, dict) and "items" in response_data:
                return response_data["items"]
            elif isinstance(response_data, list):
                return response_data
            else:
                raise ValueError("Invalid response format")
        except json.JSONDecodeError as e:
            logger.warning(f"Failed to parse JSON response ({e}), falling back to text parsing")
            # Fallback: create items from response text
            return [{"content": response_text.strip(), "type": "fact"}]
        except Exception as e:
            logger.error(f"Error parsing extraction response: {e}")
            # Fallback: create items from response text
            return [{"content": response_text.strip(), "type": "fact"}]
    
    def _process_extracted_item(self, item: Dict[str, Any], session_id: str, message_count: int) -> Dict[str, Any]:
        """Process an extracted item with confidence scoring and metadata."""
        # Ensure required fields
        processed_item = {
            "id": item.get("id", f"fact_{int(time.time() * 1000)}_{hash(str(item)) % 10000}"),
            "session_id": session_id,
            "content": item.get("content", ""),
            "type": item.get("type", "fact"),
"extracted_at": datetime.now(timezone.utc).isoformat(),
            "confidence": item.get("confidence", self._calculate_confidence(item.get("content", ""), item.get("type", "fact"))),
            "source_message_index": min(item.get("source_message_index", 0), message_count - 1),
            "project": item.get("project", "default"),
            "supersede_id": item.get("supersede_id"),
            "needs_review": item.get("needs_review", False),
        }
        
        return processed_item
    
    def _calculate_confidence(self, content: str, content_type: str) -> float:
        """Calculate confidence score based on content and explicit mentions."""
        content_lower = content.lower()
        
        # Explicit user mentions get highest confidence
        explicit_indicators = [
            "remember that", "i want", "i prefer", "let's decide", "make sure to",
            "important:", "note:", "reminder:", "don't forget", "always",
            "never", "must", "should", "will", "going to"
        ]
        
        for indicator in explicit_indicators:
            if indicator in content_lower:
                return 0.95
        
        # High-confidence inferred items
        high_confidence_types = ["decision", "preference"]
        if content_type in high_confidence_types:
            return 0.8
        
        # Check for action items or clear facts
        action_indicators = ["todo", "task", "fix", "implement", "add", "create", "update", "delete"]
        if any(indicator in content_lower for indicator in action_indicators):
            return 0.8
        
        # Default confidence for unclear content
        return 0.5
    
    async def _fallback_extraction(self, session_id: str, messages: List[str]) -> List[Dict[str, Any]]:
        """Fallback extraction when LLM fails."""
        facts = []
        
        for i, message in enumerate(messages):
            if not message.strip():
                continue
            
            # Simple fact extraction as fallback
            fact = {
                "id": f"fact_{int(time.time() * 1000)}_{i}",
                "session_id": session_id,
                "content": message,
                "type": "fact",
"extracted_at": datetime.now(timezone.utc).isoformat(),
                "confidence": 0.5,  # Lower confidence for fallback
                "source_message_index": i,
                "project": "default",
                "supersede_id": None,
                "needs_review": True,  # Mark as needing review
            }
            
            facts.append(fact)
        
        return facts

    async def _store_facts(self, session_id: str, facts: List[Dict[str, Any]]) -> None:
        """Store extracted facts in the SQLite store with deduplication."""
        for fact in facts:
            try:
                # Check for duplicates before storing
                duplicate_check = await self._check_for_duplicate(session_id, fact)
                
                if duplicate_check["should_supersede"]:
                    # Supersede the existing item
                    await self._supersede_existing_fact(session_id, fact, duplicate_check["supersede_id"])
                    logger.info(f"Superseded existing fact {duplicate_check['supersede_id']} with {fact['id']}")
                elif not duplicate_check["is_duplicate"]:
                    # Store new fact
                    await self._sqlite_store.add_memory(
                        session_id,
                        json.dumps(fact, ensure_ascii=False),
                        {"type": "extracted_fact", "fact_id": fact["id"]},
                        expires_in_hours=24 * 7,  # Facts expire after 1 week
                    )
                    logger.debug(f"Stored new fact {fact['id']}")
                else:
                    logger.debug(f"Fact {fact['id']} is duplicate, skipping")
                    
            except Exception as e:
                logger.error(f"Failed to store fact {fact.get('id', 'unknown')}: {e}")
    
    async def _check_for_duplicate(self, session_id: str, fact: Dict[str, Any]) -> Dict[str, Any]:
        """Check if a fact already exists or is similar to existing ones."""
        try:
            # Search for similar facts using FTS5
            search_terms = self._extract_search_terms(fact["content"])
            search_query = " OR ".join(search_terms)
            
            existing_facts = await self._sqlite_store.search_memories(
                session_id,
                search_query,
                limit=10,
            )
            
            best_match = None
            best_similarity = 0.0
            
            for existing_fact in existing_facts:
                similarity = self._calculate_similarity(fact["content"], existing_fact["content"])
                if similarity > best_similarity:
                    best_similarity = similarity
                    best_match = existing_fact
            
            # Determine if we should supersede or skip
            if best_similarity > 0.8:
                return {
                    "is_duplicate": True,
                    "should_supersede": True,
                    "supersede_id": best_match["id"],
                    "similarity": best_similarity
                }
            elif best_similarity > 0.6:
                return {
                    "is_duplicate": False,
                    "should_supersede": False,
                    "supersede_id": None,
                    "similarity": best_similarity
                }
            else:
                return {
                    "is_duplicate": False,
                    "should_supersede": False,
                    "supersede_id": None,
                    "similarity": best_similarity
                }
                
        except Exception as e:
            logger.error(f"Error checking for duplicates: {e}")
            return {
                "is_duplicate": False,
                "should_supersede": False,
                "supersede_id": None,
                "similarity": 0.0
            }
    
    def _extract_search_terms(self, content: str) -> List[str]:
        """Extract meaningful search terms from content for FTS5."""
        # Simple approach: split into words and filter out common terms
        import re
        words = re.findall(r'\b\w+\b', content.lower())
        
        # Filter out very common words and short terms
        stop_words = {"the", "a", "an", "and", "or", "but", "in", "on", "at", "to", "for", "of", "with", "by", "is", "are", "was", "were", "be", "been", "have", "has", "had", "do", "does", "did", "will", "would", "could", "should", "may", "might", "can", "this", "that", "these", "those", "it", "its", "they", "them", "their", "what", "which", "who", "when", "where", "why", "how", "not", "no", "yes", "true", "false"}
        
        meaningful_terms = [word for word in words if len(word) > 2 and word not in stop_words]
        
        # Return unique terms
        return list(set(meaningful_terms))
    
    def _calculate_similarity(self, text1: str, text2: str) -> float:
        """Calculate similarity between two texts."""
        import re
        
        # Simple word-based similarity
        words1 = set(re.findall(r'\b\w+\b', text1.lower()))
        words2 = set(re.findall(r'\b\w+\b', text2.lower()))
        
        if not words1 or not words2:
            return 0.0
        
        intersection = words1.intersection(words2)
        union = words1.union(words2)
        
        # Jaccard similarity
        similarity = len(intersection) / len(union)
        return similarity
    
    async def _supersede_existing_fact(self, session_id: str, new_fact: Dict[str, Any], existing_fact_id: str) -> None:
        """Supersede an existing fact with a new one."""
        try:
            # Mark the existing fact as superseded
            await self._sqlite_store.supersede_memory(
                session_id,
                existing_fact_id,
                {"superseded_by": new_fact["id"]}
            )
            
            # Store the new fact
            await self._sqlite_store.add_memory(
                session_id,
                json.dumps(new_fact, ensure_ascii=False),
                {"type": "extracted_fact", "fact_id": new_fact["id"], "superseded": existing_fact_id},
                expires_in_hours=24 * 7,
            )
            
        except Exception as e:
            logger.error(f"Failed to supersede fact {existing_fact_id}: {e}")
            # If superseding fails, just store the new fact normally
            await self._sqlite_store.add_memory(
                session_id,
                json.dumps(new_fact, ensure_ascii=False),
                {"type": "extracted_fact", "fact_id": new_fact["id"]},
                expires_in_hours=24 * 7,
            )

    async def get_extracted_facts(
        self, session_id: str, limit: int = 50
    ) -> List[Dict[str, Any]]:
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
            "oldest_extraction": oldest["created_at"] if oldest else None,
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
