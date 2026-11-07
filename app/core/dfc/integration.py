"""DFC integration with existing OryaAgent components."""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from app.core.dfc import DFC, get_dfc, initialize_dfc
from app.core.dfc.metrics import get_dfc_metrics
from app.core.observability.spans import emit_span

logger = logging.getLogger(__name__)


class DFCIntegration:
    """Integration layer for DFC with existing components."""
    
    def __init__(self, dfc: DFC):
        self.dfc = dfc
        self.metrics = get_dfc_metrics()
    
    async def initialize_from_session(self, session_id: str, session_state: Dict[str, Any]) -> None:
        """Initialize DFC from session state."""
        with emit_span("dfc.initialize_from_session", {"session_id": session_id}):
            # Load session history into DFC layers
            await self._load_session_history(session_state)
            
            # Initialize background compactor
            await self.dfc.start_background_compactor()
            
            logger.info(f"DFC initialized for session {session_id}")
    
    async def promote_tool_result(self, tool_name: str, result: Any) -> None:
        """Promote tool result to HOT layer."""
        with emit_span("dfc.promote_tool_result", {"tool_name": tool_name}):
            # Convert result to string representation
            result_str = self._serialize_result(result)
            
            # Promote to HOT
            self.dfc.promote_to_hot(tool_name, result_str)
            
            # Update metrics
            self.metrics.increment_promote_to_hot()
            
            # Save to Redis
            await self.dfc.save_to_redis()
            
            logger.debug(f"Promoted tool result {tool_name} to HOT layer")
    
    async def promote_memory_item(self, memory_item: Any) -> None:
        """Promote memory item to HOT layer."""
        with emit_span("dfc.promote_memory_item", {"memory_type": type(memory_item).__name__}):
            # Convert memory item to string representation
            item_str = self._serialize_memory_item(memory_item)
            
            # Promote to HOT
            memory_key = f"memory_{memory_item.id}"
            self.dfc.promote_to_hot(memory_key, item_str)
            
            # Update metrics
            self.metrics.increment_promote_to_hot()
            
            # Save to Redis
            await self.dfc.save_to_redis()
            
            logger.debug(f"Promoted memory item {memory_item.id} to HOT layer")
    
    def get_context_for_prompt(self, plan: Dict[str, Any]) -> str:
        """Get context for system prompt."""
        with emit_span("dfc.get_context_for_prompt"):
            # Assemble HOT context
            hot_context = self.dfc.assemble_hot(plan)
            
            # Update metrics
            self.metrics.update_layer_sizes(
                hot_size=self.dfc._get_hot_size(),
                warm_size=self.dfc._get_warm_size(),
                cold_size=len(self.dfc.cold),
                heat_cache_size=self.dfc.heat._get_size()
            )
            
            return hot_context
    
    async def create_session_snapshot(self, session_id: str) -> Dict[str, Any]:
        """Create snapshot of DFC state for session."""
        with emit_span("dfc.create_session_snapshot", {"session_id": session_id}):
            # Create snapshot
            snapshot = self.dfc.snapshot()
            
            # Convert to serializable format
            snapshot_data = {
                "hot": list(snapshot.hot.items()),
                "warm": list(snapshot.warm.items()),
                "cold": [
                    {
                        "content_hash": item.content_hash,
                        "summary": item.summary,
                        "metadata": item.metadata
                    }
                    for item in snapshot.cold
                ],
                "heat_cache_stats": snapshot.heat.get_stats()
            }
            
            # Update metrics
            self.metrics.observe_snapshot_duration(0.1)  # Mock duration
            
            return snapshot_data
    
    def _load_session_history(self, session_state: Dict[str, Any]) -> None:
        """Load session history into DFC layers."""
        # In a real implementation, this would load from session store
        # For now, we'll use mock data
        logger.info("Loading session history into DFC")
        
        # Load recent tool results into HOT
        if "recent_tool_results" in session_state:
            for tool_name, result in session_state["recent_tool_results"].items():
                self.dfc.promote_to_hot(tool_name, str(result))
        
        # Load memory items into WARM
        if "memory_items" in session_state:
            for item in session_state["memory_items"][-10:]:  # Last 10 items
                memory_key = f"memory_{item.id}"
                self.dfc.warm[memory_key] = str(item)
    
    def _serialize_result(self, result: Any) -> str:
        """Serialize tool result to string."""
        if hasattr(result, 'to_dict'):
            return str(result.to_dict())
        elif hasattr(result, '__dict__'):
            return str(result.__dict__)
        else:
            return str(result)
    
    def _serialize_memory_item(self, memory_item: Any) -> str:
        """Serialize memory item to string."""
        if hasattr(memory_item, 'to_markdown'):
            return memory_item.to_markdown()
        elif hasattr(memory_item, 'content'):
            return memory_item.content
        else:
            return str(memory_item)


# Global integration instance
_dfc_integration: Optional[DFCIntegration] = None


def get_dfc_integration() -> DFCIntegration:
    """Get global DFC integration instance."""
    global _dfc_integration
    if _dfc_integration is None:
        dfc = get_dfc()
        _dfc_integration = DFCIntegration(dfc)
    return _dfc_integration


def initialize_dfc_integration(
    ukb_router: Any = None,
    lsp_bus: Any = None,
    memory: Any = None,
    redis_client: Any = None,
) -> DFCIntegration:
    """Initialize DFC integration with dependencies."""
    # Initialize DFC
    dfc = initialize_dfc(
        ukb_router=ukb_router,
        lsp_bus=lsp_bus,
        memory=memory,
        redis_client=redis_client,
    )
    
    # Create integration
    global _dfc_integration
    _dfc_integration = DFCIntegration(dfc)
    
    return _dfc_integration