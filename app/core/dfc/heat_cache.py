"""HeatCache - predicted HOT layer for DFC."""

from __future__ import annotations

import logging
from collections import OrderedDict
from typing import Optional

logger = logging.getLogger(__name__)


class HeatCache:
    """Predicted HOT layer (placeholder in BETA, full impl in PROD)."""

    def __init__(self, max_size: int = 4000):
        self.max_size = max_size
        self.cache: OrderedDict[str, str] = OrderedDict()
        self.hits = 0
        self.misses = 0

    def get(self, key: str) -> Optional[str]:
        """Get value from heat cache."""
        if key in self.cache:
            self.cache.move_to_end(key)
            self.hits += 1
            logger.debug(f"HeatCache hit for key: {key}")
            return self.cache[key]
        else:
            self.misses += 1
            logger.debug(f"HeatCache miss for key: {key}")
            return None

    def put(self, key: str, value: str) -> None:
        """Put value into heat cache."""
        self.cache[key] = value
        self.cache.move_to_end(key)

        # Evict oldest if over size
        while self._get_size() > self.max_size:
            oldest_key = next(iter(self.cache))
            self.cache.pop(oldest_key)
            logger.debug(f"HeatCache evicted oldest key: {oldest_key}")

    def _get_size(self) -> int:
        """Get current size in tokens (simplified)."""
        return sum(len(str(v)) for v in self.cache.values())

    def clear(self) -> None:
        """Clear all items from cache."""
        self.cache.clear()
        self.hits = 0
        self.misses = 0

    def get_stats(self) -> dict:
        """Get cache statistics."""
        total_requests = self.hits + self.misses
        hit_rate = (self.hits / total_requests) if total_requests > 0 else 0

        return {
            "size": self._get_size(),
            "max_size": self.max_size,
            "items": len(self.cache),
            "hits": self.hits,
            "misses": self.misses,
            "hit_rate": hit_rate,
        }
