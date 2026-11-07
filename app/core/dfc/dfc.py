"""DFC: Dynamic Fast Context - 5 layers (HEAT/HOT/WARM/COLD/ICE) + BackgroundCompactor."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Union

import redis.asyncio as redis
from fastapi import Depends
from pydantic import BaseModel

from app.core.observability.spans import emit_span

logger = logging.getLogger(__name__)


@dataclass
class CompactSummary:
    """Compact summary for COLD layer."""
    content_hash: str
    summary: str
    metadata: Dict[str, Any] = field(default_factory=dict)


class HeatCache:
    """Predicted HOT layer (placeholder in BETA, full impl in PROD)."""
    
    def __init__(self, max_size: int = 4000):
        self.max_size = max_size
        self.cache: OrderedDict[str, str] = OrderedDict()
    
    def get(self, key: str) -> Optional[str]:
        """Get value from heat cache."""
        if key in self.cache:
            self.cache.move_to_end(key)
            return self.cache[key]
        return None
    
    def put(self, key: str, value: str) -> None:
        """Put value into heat cache."""
        self.cache[key] = value
        self.cache.move_to_end(key)
        
        # Evict oldest if over size
        while self._get_size() > self.max_size:
            oldest_key = next(iter(self.cache))
            self.cache.pop(oldest_key)
    
    def _get_size(self) -> int:
        """Get current size in tokens (simplified)."""
        return sum(len(str(v)) for v in self.cache.values())


class DFC:
    """Dynamic Fast Context - 5 layers: HEAT/HOT/WARM/COLD/ICE."""
    
    def __init__(
        self,
        ukb_router: Any = None,  # UKBRouter from B-27
        lsp_bus: Any = None,     # LSPBus from B-26
        memory: Any = None,      # SQLiteStore from B-21
        redis_client: redis.Redis = None,
        max_hot_size: int = 8000,
        max_warm_size: int = 32000,
        heat_cache_size: int = 4000,
    ):
        self.ukb_router = ukb_router
        self.lsp_bus = lsp_bus
        self.memory = memory
        self.redis_client = redis_client
        
        # Layer sizes
        self.max_hot_size = max_hot_size
        self.max_warm_size = max_warm_size
        self.heat_cache_size = heat_cache_size
        
        # Layers
        self.heat = HeatCache(max_size=heat_cache_size)
        self.hot: OrderedDict[str, str] = OrderedDict()
        self.warm: OrderedDict[str, str] = OrderedDict()
        self.cold: List[CompactSummary] = []
        
        # Background compactor
        self.compactor = BackgroundCompactor(self)
        self.compactor_task: Optional[asyncio.Task] = None
    
    async def initialize(self) -> None:
        """Initialize DFC from Redis."""
        if not self.redis_client:
            return
        
        try:
            # Load HOT layer
            hot_data = await self.redis_client.get(f"orya:dfc:hot:{id(self)}")
            if hot_data:
                hot_json = json.loads(hot_data)
                self.hot = OrderedDict(hot_json)
            
            # Load WARM layer
            warm_data = await self.redis_client.get(f"orya:dfc:warm:{id(self)}")
            if warm_data:
                warm_json = json.loads(warm_data)
                self.warm = OrderedDict(warm_json)
            
            logger.info("DFC initialized from Redis")
            
        except Exception as e:
            logger.error(f"Error initializing DFC from Redis: {e}")
    
    async def save_to_redis(self) -> None:
        """Save DFC state to Redis."""
        if not self.redis_client:
            return
        
        try:
            # Save HOT layer
            await self.redis_client.set(
                f"orya:dfc:hot:{id(self)}",
                json.dumps(list(self.hot.items())),
                ex=3600  # 1 hour TTL
            )
            
            # Save WARM layer
            await self.redis_client.set(
                f"orya:dfc:warm:{id(self)}",
                json.dumps(list(self.warm.items())),
                ex=3600  # 1 hour TTL
            )
            
        except Exception as e:
            logger.error(f"Error saving DFC to Redis: {e}")
    
    def assemble_hot(self, plan: Dict[str, Any]) -> str:
        """Assemble HOT context from plan and layers."""
        with emit_span("dfc.assemble_hot", {
            "dfc.hot_size_tokens": self._get_hot_size(),
            "dfc.warm_size_tokens": self._get_warm_size(),
            "dfc.cold_size": len(self.cold),
        }) as span:
            # Start with cacheable prefix (from plan)
            cacheable_prefix = plan.get("cacheable_prefix", "")
            
            # Add dynamic suffix from HOT layer
            dynamic_suffix = []
            for key, value in self.hot.items():
                dynamic_suffix.append(f"{key}: {value}")
            
            # Add prefetch hints from plan
            prefetch_hints = plan.get("prefetch_hints", [])
            if prefetch_hints:
                dynamic_suffix.append("Prefetch hints:")
                for hint in prefetch_hints:
                    dynamic_suffix.append(f"- {hint}")
            
            # Combine everything
            hot_context = "\n".join([
                cacheable_prefix,
                *dynamic_suffix,
            ])
            
            span.set_attribute("dfc.hot_size_tokens", self._get_hot_size())
            span.set_attribute("dfc.warm_demoted", len(self.warm))
            span.set_attribute("dfc.cold_compacted", len(self.cold))
            
            return hot_context
    
    def promote_to_hot(self, key: str, value: str) -> None:
        """Promote item to HOT layer with demotion to WARM if needed."""
        # Add to HOT
        self.hot[key] = value
        self.hot.move_to_end(key)
        
        # Demote oldest to WARM if over size
        while self._get_hot_size() > self.max_hot_size:
            oldest_key = next(iter(self.hot))
            oldest_value = self.hot.pop(oldest_key)
            self.warm[oldest_key] = oldest_value
            self.warm.move_to_end(oldest_key)
    
    def snapshot(self) -> "DFC":
        """Create immutable snapshot of DFC state."""
        snapshot = DFC(
            ukb_router=self.ukb_router,
            lsp_bus=self.lsp_bus,
            memory=self.memory,
            redis_client=self.redis_client,
            max_hot_size=self.max_hot_size,
            max_warm_size=self.max_warm_size,
            heat_cache_size=self.heat_cache_size,
        )
        
        # Copy layers (deep copy for immutability)
        snapshot.heat = HeatCache(max_size=self.heat_cache_size)
        snapshot.heat.cache = OrderedDict(self.heat.cache)
        
        snapshot.hot = OrderedDict(self.hot)
        snapshot.warm = OrderedDict(self.warm)
        snapshot.cold = list(self.cold)
        
        return snapshot
    
    def _get_hot_size(self) -> int:
        """Get HOT layer size in tokens (simplified)."""
        return sum(len(str(v)) for v in self.hot.values())
    
    def _get_warm_size(self) -> int:
        """Get WARM layer size in tokens (simplified)."""
        return sum(len(str(v)) for v in self.warm.values())
    
    async def start_background_compactor(self) -> None:
        """Start background compactor task."""
        if self.compactor_task and not self.compactor_task.done():
            return
        
        self.compactor_task = asyncio.create_task(self.compactor.run())
    
    async def stop_background_compactor(self) -> None:
        """Stop background compactor task."""
        if self.compactor_task and not self.compactor_task.done():
            self.compactor_task.cancel()
            try:
                await self.compactor_task
            except asyncio.CancelledError:
                pass


class BackgroundCompactor:
    """Background compactor for WARM→COLD transitions."""
    
    def __init__(self, dfc: DFC):
        self.dfc = dfc
        self.compaction_interval = 60  # 1 minute
        self.last_compaction = 0
        self.compaction_count = 0
    
    async def run(self) -> None:
        """Run background compaction loop."""
        while True:
            try:
                await asyncio.sleep(self.compaction_interval)
                await self.compact_if_needed()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in background compactor: {e}")
    
    async def compact_if_needed(self) -> None:
        """Compact WARM→COLD if needed."""
        current_time = time.time()
        
        # Compact after 10 turns or every minute
        if (current_time - self.last_compaction > 60 or 
            len(self.dfc.warm) > 100):  # Or some other trigger
            
            await self.compact_warm_to_cold()
            self.last_compaction = current_time
            self.compaction_count += 1
    
    async def compact_warm_to_cold(self) -> None:
        """Compact oldest items from WARM to COLD."""
        with emit_span("dfc.compact", {
            "dfc.warm_size_before": len(self.dfc.warm),
            "dfc.cold_size_before": len(self.dfc.cold),
        }) as span:
            
            # Take oldest 20% of WARM items
            items_to_compact = max(1, len(self.dfc.warm) // 5)
            items = list(self.dfc.warm.items())[:items_to_compact]
            
            # Create summaries
            for key, value in items:
                content_hash = hashlib.sha256((key + value).encode()).hexdigest()
                summary = f"Summary of {key}: {value[:100]}..."  # Simplified summary
                
                compact_summary = CompactSummary(
                    content_hash=content_hash,
                    summary=summary,
                    metadata={"original_key": key, "original_value": value}
                )
                
                self.dfc.cold.append(compact_summary)
                
                # Remove from WARM
                if key in self.dfc.warm:
                    self.dfc.warm.pop(key)
            
            span.set_attribute("dfc.warm_size_after", len(self.dfc.warm))
            span.set_attribute("dfc.cold_size_after", len(self.dfc.cold))
            span.set_attribute("dfc.compacted_items", items_to_compact)
            
            logger.info(f"Compacted {items_to_compact} items from WARM to COLD")


# Global DFC instance
_dfc_instance: Optional[DFC] = None


def get_dfc() -> DFC:
    """Get global DFC instance."""
    if _dfc_instance is None:
        raise RuntimeError("DFC not initialized")
    return _dfc_instance


def initialize_dfc(
    ukb_router: Any = None,
    lsp_bus: Any = None,
    memory: Any = None,
    redis_client: redis.Redis = None,
) -> DFC:
    """Initialize global DFC instance."""
    global _dfc_instance
    
    if _dfc_instance is None:
        _dfc_instance = DFC(
            ukb_router=ukb_router,
            lsp_bus=lsp_bus,
            memory=memory,
            redis_client=redis_client,
        )
    
    return _dfc_instance