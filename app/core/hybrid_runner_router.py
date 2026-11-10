"""Hybrid GitHub Actions runner router: switch between GitHub-hosted and local runners.

This module implements the logic for switching between GitHub-hosted and 
self-hosted runners based on budget thresholds and workflow priorities.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Optional

from app.core.config import get_settings
from app.core.github_actions import (
    GitHubActionsBudget,
    GitHubActionsMonitor,
    GitHubActionsUsage,
    RunnerType,
    get_github_actions_monitor,
    should_use_local_runners,
)

__all__ = [
    "HybridRunnerRouter",
    "RunnerSelection",
    "get_runner_selection",
    "select_runner_type",
]

logger = logging.getLogger(__name__)

class RunnerSelection:
    """Result of runner type selection for a workflow."""
    
    def __init__(
        self,
        workflow_name: str,
        repository: str,
        runner_type: RunnerType,
        reason: str,
        usage: GitHubActionsUsage,
        budget: GitHubActionsBudget,
    ) -> None:
        self.workflow_name = workflow_name
        self.repository = repository
        self.runner_type = runner_type
        self.reason = reason
        self.usage = usage
        self.budget = budget
    
    def to_dict(self) -> dict[str, Any]:
        return {
            "workflow_name": self.workflow_name,
            "repository": self.repository,
            "runner_type": self.runner_type.value,
            "reason": self.reason,
            "usage": self.usage.to_dict(),
            "budget": self.budget.to_dict(),
        }

class HybridRunnerRouter:
    """Router for selecting between GitHub-hosted and self-hosted runners."""
    
    def __init__(self, monitor: GitHubActionsMonitor) -> None:
        self.monitor = monitor
        self._cache: dict[str, RunnerSelection] = {}
        self._cache_ttl = 60  # Cache results for 60 seconds
        self._last_cache_update = 0
    
    async def select_runner(
        self,
        workflow_name: str,
        repository: str,
    ) -> RunnerSelection:
        """Select the appropriate runner type for a workflow."""
        # Check cache first
        cache_key = f"{repository}:{workflow_name}"
        current_time = asyncio.get_event_loop().time()
        
        if cache_key in self._cache and (current_time - self._last_cache_update) < self._cache_ttl:
            return self._cache[cache_key]
        
        # Get current usage and budget
        usage = await self.monitor.get_workflow_usage(workflow_name, repository)
        budget = await self.monitor.get_workflow_budget(workflow_name, repository)
        
        # Determine runner type based on budget and priorities
        runner_type, reason = await self._determine_runner_type(workflow_name, repository, usage, budget)
        
        # Create selection result
        selection = RunnerSelection(
            workflow_name=workflow_name,
            repository=repository,
            runner_type=runner_type,
            reason=reason,
            usage=usage,
            budget=budget,
        )
        
        # Update cache
        self._cache[cache_key] = selection
        self._last_cache_update = current_time
        
        return selection
    
    async def _determine_runner_type(
        self,
        workflow_name: str,
        repository: str,
        usage: GitHubActionsUsage,
        budget: GitHubActionsBudget,
    ) -> tuple[RunnerType, str]:
        """Determine the best runner type based on budget and priorities."""
        
        # Check if local runners are available and healthy
        local_runners_available = await self._check_local_runner_availability()
        
        # If budget is exceeded, must use local runners
        if usage.minutes_used >= budget.monthly_minutes:
            if local_runners_available:
                return RunnerType.SELF_HOSTED, "budget_exceeded"
            else:
                # Fallback to GitHub-hosted if local runners are not available
                logger.warning(
                    "Budget exceeded but local runners not available for %s/%s",
                    repository,
                    workflow_name,
                )
                return RunnerType.GITHUB_HOSTED, "budget_exceeded_fallback"
        
        # Check if approaching threshold and should switch
        threshold = get_settings().github_actions_switch_threshold
        if usage.minutes_used >= budget.monthly_minutes * threshold:
            if local_runners_available:
                return RunnerType.SELF_HOSTED, "threshold_reached"
        
        # Check workflow priority - high priority workflows always use GitHub-hosted
        if budget.priority == 1:  # Highest priority
            return RunnerType.GITHUB_HOSTED, "high_priority"
        
        # Default to GitHub-hosted
        return RunnerType.GITHUB_HOSTED, "default"
    
    async def _check_local_runner_availability(self) -> bool:
        """Check if local runners are available and healthy."""
        settings = get_settings()
        
        if not settings.local_runners_enabled:
            return False
        
        # In a real implementation, this would check actual runner health
        # For now, we'll simulate health checks
        try:
            # Simulate health check delay
            await asyncio.sleep(0.1)
            return True
        except Exception:
            return False
    
    async def get_runner_selections(self) -> dict[str, RunnerSelection]:
        """Get runner selections for all configured workflows."""
        settings = get_settings()
        selections = {}
        
        if hasattr(settings, 'github_actions_workflows'):
            for workflow_config in settings.github_actions_workflows:
                workflow_name = workflow_config.get('name')
                repository = workflow_config.get('repository', 'default')
                
                if workflow_name:
                    selection = await self.select_runner(workflow_name, repository)
                    selections[f"{repository}:{workflow_name}"] = selection
        
        return selections
    
    async def optimize_runner_allocation(self) -> dict[str, RunnerSelection]:
        """Optimize runner allocation across all workflows based on budget."""
        settings = get_settings()
        
        # Get all workflow selections
        selections = await self.get_runner_selections()
        
        # Calculate total usage
        total_usage = sum(sel.usage.minutes_used for sel in selections.values())
        total_budget = sum(sel.budget.monthly_minutes for sel in selections.values())
        
        # If we're approaching the overall budget, optimize allocation
        if total_usage >= total_budget * 0.8:
            logger.info("Optimizing runner allocation due to high budget usage")
            
            # Prioritize critical workflows on GitHub-hosted
            for selection in selections.values():
                if selection.budget.priority == 1:  # Critical
                    selection.runner_type = RunnerType.GITHUB_HOSTED
                    selection.reason = "critical_priority"
        
        return selections

# Global router instance
_hybrid_runner_router: Optional[HybridRunnerRouter] = None

def get_hybrid_runner_router() -> HybridRunnerRouter:
    """Get the global hybrid runner router instance."""
    if _hybrid_runner_router is None:
        raise RuntimeError("Hybrid runner router not initialized")
    return _hybrid_runner_router

def init_hybrid_runner_router() -> None:
    """Initialize the hybrid runner router."""
    global _hybrid_runner_router
    
    monitor = get_github_actions_monitor()
    _hybrid_runner_router = HybridRunnerRouter(monitor)
    
    logger.info("Hybrid runner router initialized")

async def close_hybrid_runner_router() -> None:
    """Close the hybrid runner router."""
    global _hybrid_runner_router
    
    _hybrid_runner_router = None
    logger.info("Hybrid runner router closed")

# Convenience functions
async def select_runner_type(
    workflow_name: str,
    repository: str,
) -> RunnerType:
    """Select the appropriate runner type for a workflow."""
    router = get_hybrid_runner_router()
    selection = await router.select_runner(workflow_name, repository)
    return selection.runner_type

async def get_runner_selection(
    workflow_name: str,
    repository: str,
) -> RunnerSelection:
    """Get runner selection for a specific workflow."""
    router = get_hybrid_runner_router()
    return await router.select_runner(workflow_name, repository)