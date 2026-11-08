"""BackgroundCompactor - WARM→COLD transitions for DFC."""

from __future__ import annotations

import asyncio
import logging
import time
from typing import TYPE_CHECKING

from app.core.observability.spans import emit_span

if TYPE_CHECKING:
    from .dfc import DFC

logger = logging.getLogger(__name__)


class BackgroundCompactor:
    """Background compactor for WARM→COLD transitions."""

    def __init__(self, dfc: "DFC"):
        self.dfc = dfc
        self.compaction_interval = 60  # 1 minute
        self.last_compaction = 0
        self.compaction_count = 0
        self.is_running = False

    async def run(self) -> None:
        """Run background compaction loop."""
        self.is_running = True
        logger.info("Background compactor started")

        while self.is_running:
            try:
                await asyncio.sleep(self.compaction_interval)
                await self.compact_if_needed()
            except asyncio.CancelledError:
                logger.info("Background compactor cancelled")
                break
            except Exception as e:
                logger.error(f"Error in background compactor: {e}")

        logger.info("Background compactor stopped")

    def stop(self) -> None:
        """Stop background compactor."""
        self.is_running = False

    async def compact_if_needed(self) -> None:
        """Compact WARM→COLD if needed."""
        current_time = time.time()

        # Compact after 10 turns or every minute
        if (
            current_time - self.last_compaction > 60 or len(self.dfc.warm) > 100
        ):  # Or some other trigger
            await self.compact_warm_to_cold()
            self.last_compaction = current_time
            self.compaction_count += 1

    async def compact_warm_to_cold(self) -> None:
        """Compact oldest items from WARM to COLD."""
        with emit_span(
            "dfc.compact",
            {
                "dfc.warm_size_before": len(self.dfc.warm),
                "dfc.cold_size_before": len(self.dfc.cold),
            },
        ) as span:
            # Take oldest 20% of WARM items
            items_to_compact = max(1, len(self.dfc.warm) // 5)
            items = list(self.dfc.warm.items())[:items_to_compact]

            logger.info(f"Compacting {items_to_compact} items from WARM to COLD")

            # Create summaries
            for key, value in items:
                content_hash = self._generate_content_hash(key, value)
                summary = self._create_summary(key, value)

                # Add to COLD layer
                self.dfc.cold.append(summary)

                # Remove from WARM
                if key in self.dfc.warm:
                    self.dfc.warm.pop(key)

            span.set_attribute("dfc.warm_size_after", len(self.dfc.warm))
            span.set_attribute("dfc.cold_size_after", len(self.dfc.cold))
            span.set_attribute("dfc.compacted_items", items_to_compact)

            logger.info(f"Compacted {items_to_compact} items from WARM to COLD")

    def _generate_content_hash(self, key: str, value: str) -> str:
        """Generate content hash for deduplication."""
        import hashlib

        content = f"{key}:{value}"
        return hashlib.sha256(content.encode()).hexdigest()

    def _create_summary(self, key: str, value: str) -> "CompactSummary":
        """Create compact summary for COLD layer."""
        from .dfc import CompactSummary

        content_hash = self._generate_content_hash(key, value)
        summary_text = f"Summary of {key}: {value[:100]}..."  # Simplified summary

        return CompactSummary(
            content_hash=content_hash,
            summary=summary_text,
            metadata={"original_key": key, "original_value": value},
        )
