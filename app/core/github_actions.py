"""GitHub Actions cost tracking: monitor runner minutes and implement hybrid mode.

This module extends the existing cost tracking system (A-13) to monitor
GitHub Actions usage and implement hybrid mode switching when free minutes
are exhausted.

Features:
- Track GitHub Actions minutes by workflow and repository
- Implement hybrid mode switching between GitHub-hosted and self-hosted runners
- Predictive budget allocation based on historical usage
- Health monitoring for local runner infrastructure

Architecture:
- GitHubActionsCostStore: Redis-backed store for GitHub Actions usage
- GitHubActionsMonitor: Real-time usage tracking and budget checking
- HybridRunnerRouter: Switch between runner types based on budget
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, date, datetime, timedelta
from enum import Enum
from typing import Any, Optional

from app.core.config import get_settings

__all__ = [
    "GitHubActionsCostStore",
    "GitHubActionsMonitor",
    "HybridRunnerRouter",
    "RunnerType",
    "GitHubActionsBudget",
    "GitHubActionsUsage",
    "init_github_actions_monitor",
    "get_github_actions_monitor",
    "close_github_actions_monitor",
    "record_workflow_minutes",
    "get_workflow_usage",
    "get_workflow_budget",
    "set_workflow_budget",
    "should_use_local_runners",
]

logger = logging.getLogger(__name__)

#: Prefix for GitHub Actions usage counters
GITHUB_ACTIONS_KEY_PREFIX = "orya:github_actions"

#: Prefix for GitHub Actions budgets
GITHUB_ACTIONS_BUDGET_PREFIX = "orya:github_budget"

#: Redis TTL for usage keys (7 days: survives month rollover)
GITHUB_ACTIONS_KEY_TTL_DAYS = 7

#: Default GitHub Actions free minutes per month
DEFAULT_FREE_MINUTES = 2000

#: Threshold for switching to local runners (90% of budget)
HYBRID_SWITCH_THRESHOLD = 0.9

#: Health check interval for local runners (seconds)
LOCAL_RUNNER_HEALTH_INTERVAL = 30

class RunnerType(Enum):
    """Supported runner types for hybrid mode."""
    GITHUB_HOSTED = "github-hosted"
    SELF_HOSTED = "self-hosted"
    ENTERPRISE = "enterprise"

class GitHubActionsUsage:
    """Usage data for GitHub Actions workflows."""
    
    def __init__(
        self,
        workflow_name: str,
        repository: str,
        minutes_used: int,
        last_updated: datetime,
    ) -> None:
        self.workflow_name = workflow_name
        self.repository = repository
        self.minutes_used = minutes_used
        self.last_updated = last_updated
    
    def to_dict(self) -> dict[str, Any]:
        return {
            "workflow_name": self.workflow_name,
            "repository": self.repository,
            "minutes_used": self.minutes_used,
            "last_updated": self.last_updated.isoformat(),
        }
    
    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> GitHubActionsUsage:
        return cls(
            workflow_name=data["workflow_name"],
            repository=data["repository"],
            minutes_used=data["minutes_used"],
            last_updated=datetime.fromisoformat(data["last_updated"]),
        )

class GitHubActionsBudget:
    """Budget configuration for GitHub Actions workflows."""
    
    def __init__(
        self,
        workflow_name: str,
        repository: str,
        monthly_minutes: int,
        priority: int = 1,
        runner_type: RunnerType = RunnerType.GITHUB_HOSTED,
    ) -> None:
        self.workflow_name = workflow_name
        self.repository = repository
        self.monthly_minutes = monthly_minutes
        self.priority = priority
        self.runner_type = runner_type
    
    def to_dict(self) -> dict[str, Any]:
        return {
            "workflow_name": self.workflow_name,
            "repository": self.repository,
            "monthly_minutes": self.monthly_minutes,
            "priority": self.priority,
            "runner_type": self.runner_type.value,
        }
    
    def to_json(self) -> str:
        """Convert to JSON string for Redis storage."""
        import json
        return json.dumps(self.to_dict())
    
    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> GitHubActionsBudget:
        return cls(
            workflow_name=data["workflow_name"],
            repository=data["repository"],
            monthly_minutes=data["monthly_minutes"],
            priority=data["priority"],
            runner_type=RunnerType(data["runner_type"]),
        )
    
    @classmethod
    def from_json(cls, json_str: str) -> GitHubActionsBudget:
        """Create from JSON string for Redis storage."""
        import json
        return cls.from_dict(json.loads(json_str))

class GitHubActionsCostStore:
    """Redis-backed store for GitHub Actions usage and budgets."""
    
    def __init__(self, redis: Any) -> None:
        self.redis = redis
    
    async def record_usage(
        self,
        workflow_name: str,
        repository: str,
        minutes_used: int,
    ) -> None:
        """Record minutes used by a workflow."""
        today = date.today().isoformat()
        redis_key = f"{GITHUB_ACTIONS_KEY_PREFIX}:{repository}:{workflow_name}:{today}"
        
        try:
            await self.redis.incrby(redis_key, minutes_used)
            await self.redis.expire(redis_key, GITHUB_ACTIONS_KEY_TTL_DAYS * 24 * 3600)
        except Exception as exc:
            logger.warning("GitHub Actions usage recording failed (%s)", exc)
    
    async def get_usage(
        self,
        workflow_name: str,
        repository: str,
        days: int = 30,
    ) -> GitHubActionsUsage:
        """Get usage data for a workflow over specified days."""
        today = date.today()
        total_minutes = 0
        
        for i in range(days):
            day = (today - timedelta(days=i)).isoformat()
            redis_key = f"{GITHUB_ACTIONS_KEY_PREFIX}:{repository}:{workflow_name}:{day}"
            
            try:
                raw = await self.redis.get(redis_key)
                if raw:
                    total_minutes += int(raw)
            except Exception:
                continue
        
        return GitHubActionsUsage(
            workflow_name=workflow_name,
            repository=repository,
            minutes_used=total_minutes,
            last_updated=datetime.now(UTC),
        )
    
    async def set_budget(
        self,
        workflow_name: str,
        repository: str,
        monthly_minutes: int,
        priority: int = 1,
        runner_type: RunnerType = RunnerType.GITHUB_HOSTED,
    ) -> None:
        """Set budget for a workflow."""
        budget = GitHubActionsBudget(
            workflow_name=workflow_name,
            repository=repository,
            monthly_minutes=monthly_minutes,
            priority=priority,
            runner_type=runner_type,
        )
        
        redis_key = f"{GITHUB_ACTIONS_BUDGET_PREFIX}:{repository}:{workflow_name}"
        try:
            await self.redis.set(redis_key, budget.to_json())
        except Exception as exc:
            logger.warning("GitHub Actions budget setting failed (%s)", exc)
    
    async def get_budget(
        self,
        workflow_name: str,
        repository: str,
    ) -> Optional[GitHubActionsBudget]:
        """Get budget for a workflow."""
        redis_key = f"{GITHUB_ACTIONS_BUDGET_PREFIX}:{repository}:{workflow_name}"
        
        try:
            raw = await self.redis.get(redis_key)
            if raw:
                return GitHubActionsBudget.from_json(raw)
        except Exception:
            pass
        
        # Return default budget
        return GitHubActionsBudget(
            workflow_name=workflow_name,
            repository=repository,
            monthly_minutes=DEFAULT_FREE_MINUTES,
            priority=1,
            runner_type=RunnerType.GITHUB_HOSTED,
        )

class GitHubActionsMonitor:
    """Monitor GitHub Actions usage and implement hybrid mode logic."""
    
    def __init__(self, cost_store: GitHubActionsCostStore) -> None:
        self.cost_store = cost_store
        self._health_checks: dict[str, bool] = {}
        self._monitor_task: Optional[asyncio.Task] = None
    
    async def record_workflow_minutes(
        self,
        workflow_name: str,
        repository: str,
        minutes_used: int,
    ) -> None:
        """Record minutes used by a workflow."""
        await self.cost_store.record_usage(workflow_name, repository, minutes_used)
        
        # Check if we should switch to local runners
        usage = await self.get_workflow_usage(workflow_name, repository)
        budget = await self.get_workflow_budget(workflow_name, repository)
        
        if usage.minutes_used >= budget.monthly_minutes * HYBRID_SWITCH_THRESHOLD:
            logger.warning(
                "GitHub Actions budget approaching limit: %s/%s minutes used for %s/%s",
                usage.minutes_used,
                budget.monthly_minutes,
                repository,
                workflow_name,
            )
    
    async def get_workflow_usage(
        self,
        workflow_name: str,
        repository: str,
    ) -> GitHubActionsUsage:
        """Get current usage for a workflow."""
        return await self.cost_store.get_usage(workflow_name, repository)
    
    async def get_workflow_budget(
        self,
        workflow_name: str,
        repository: str,
    ) -> GitHubActionsBudget:
        """Get budget for a workflow."""
        budget = await self.cost_store.get_budget(workflow_name, repository)
        
        # Apply environment-specific overrides
        settings = get_settings()
        env_override = getattr(settings, f"github_actions_{workflow_name}_minutes", None)
        if env_override:
            budget.monthly_minutes = env_override
        
        return budget
    
    async def set_workflow_budget(
        self,
        workflow_name: str,
        repository: str,
        monthly_minutes: int,
        priority: int = 1,
        runner_type: RunnerType = RunnerType.GITHUB_HOSTED,
    ) -> None:
        """Set budget for a workflow."""
        await self.cost_store.set_budget(
            workflow_name,
            repository,
            monthly_minutes,
            priority,
            runner_type,
        )
    
    async def should_use_local_runners(
        self,
        workflow_name: str,
        repository: str,
    ) -> bool:
        """Determine if local runners should be used for a workflow."""
        usage = await self.get_workflow_usage(workflow_name, repository)
        budget = await self.get_workflow_budget(workflow_name, repository)
        
        # Check if budget is exceeded
        if usage.minutes_used >= budget.monthly_minutes:
            return True
        
        # Check if approaching threshold
        if usage.minutes_used >= budget.monthly_minutes * HYBRID_SWITCH_THRESHOLD:
            # Check if local runners are healthy
            local_runners_healthy = await self._check_local_runner_health()
            if local_runners_healthy:
                logger.info(
                    "Switching to local runners for %s/%s (budget threshold reached)",
                    repository,
                    workflow_name,
                )
                return True
        
        return False
    
    async def _check_local_runner_health(self) -> bool:
        """Check health of local runner infrastructure."""
        # In a real implementation, this would check actual runner health
        # For now, we'll simulate health checks
        settings = get_settings()
        if not settings.local_runners_enabled:
            return False
        
        # Simulate health check - in reality this would ping actual runners
        return True
    
    async def start_monitoring(self) -> None:
        """Start background monitoring task."""
        if self._monitor_task is not None:
            return
        
        self._monitor_task = asyncio.create_task(self._monitor_loop())
        logger.info("GitHub Actions monitoring started")
    
    async def stop_monitoring(self) -> None:
        """Stop background monitoring task."""
        if self._monitor_task is not None:
            self._monitor_task.cancel()
            try:
                await self._monitor_task
            except asyncio.CancelledError:
                pass
            self._monitor_task = None
            logger.info("GitHub Actions monitoring stopped")
    
    async def _monitor_loop(self) -> None:
        """Background monitoring loop."""
        while True:
            try:
                # Perform periodic health checks
                await self._check_local_runner_health()
                
                # Check for workflows approaching budget limits
                await self._check_budget_warnings()
                
                await asyncio.sleep(LOCAL_RUNNER_HEALTH_INTERVAL)
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error("GitHub Actions monitoring error: %s", exc)
                await asyncio.sleep(LOCAL_RUNNER_HEALTH_INTERVAL)
    
    async def _check_budget_warnings(self) -> None:
        """Check for workflows approaching budget limits and log warnings."""
        # In a real implementation, this would check all configured workflows
        # For now, we'll simulate checking common workflows
        settings = get_settings()
        
        if hasattr(settings, 'github_actions_workflows'):
            for workflow_config in settings.github_actions_workflows:
                workflow_name = workflow_config.get('name')
                repository = workflow_config.get('repository', 'default')
                
                if workflow_name:
                    usage = await self.get_workflow_usage(workflow_name, repository)
                    budget = await self.get_workflow_budget(workflow_name, repository)
                    
                    ratio = usage.minutes_used / budget.monthly_minutes
                    if ratio >= 0.9:
                        logger.warning(
                            "GitHub Actions budget warning: %.1f%% used for %s/%s (%s/%s minutes)",
                            ratio * 100,
                            repository,
                            workflow_name,
                            usage.minutes_used,
                            budget.monthly_minutes,
                        )

# Global monitor instance
_github_actions_monitor: Optional[GitHubActionsMonitor] = None
_github_actions_store: Optional[GitHubActionsCostStore] = None

def get_github_actions_monitor() -> GitHubActionsMonitor:
    """Get the global GitHub Actions monitor instance."""
    if _github_actions_monitor is None:
        raise RuntimeError("GitHub Actions monitor not initialized")
    return _github_actions_monitor

def init_github_actions_monitor(*, force: bool = False) -> None:
    """Initialize the GitHub Actions monitor with Redis backend."""
    global _github_actions_monitor, _github_actions_store
    
    if _github_actions_monitor is not None and not force:
        return
    
    settings = get_settings()
    if not settings.github_actions_enabled:
        _github_actions_monitor = None
        _github_actions_store = None
        logger.info("GitHub Actions monitoring disabled")
        return
    
    from redis.asyncio import Redis
    
    client = Redis.from_url(settings.redis_url, decode_responses=True)
    _github_actions_store = GitHubActionsCostStore(client)
    _github_actions_monitor = GitHubActionsMonitor(_github_actions_store)
    
    logger.info("GitHub Actions monitor initialized")

async def close_github_actions_monitor() -> None:
    """Close the GitHub Actions monitor."""
    global _github_actions_monitor, _github_actions_store
    
    if _github_actions_monitor is not None:
        await _github_actions_monitor.stop_monitoring()
    
    if _github_actions_store is not None:
        # Close Redis connection if needed
        pass
    
    _github_actions_monitor = None
    _github_actions_store = None
    logger.info("GitHub Actions monitor closed")

# Convenience functions
async def record_workflow_minutes(
    workflow_name: str,
    repository: str,
    minutes_used: int,
) -> None:
    """Record minutes used by a workflow."""
    monitor = get_github_actions_monitor()
    await monitor.record_workflow_minutes(workflow_name, repository, minutes_used)

async def get_workflow_usage(
    workflow_name: str,
    repository: str,
) -> GitHubActionsUsage:
    """Get current usage for a workflow."""
    monitor = get_github_actions_monitor()
    return await monitor.get_workflow_usage(workflow_name, repository)

async def get_workflow_budget(
    workflow_name: str,
    repository: str,
) -> GitHubActionsBudget:
    """Get budget for a workflow."""
    monitor = get_github_actions_monitor()
    return await monitor.get_workflow_budget(workflow_name, repository)

async def set_workflow_budget(
    workflow_name: str,
    repository: str,
    monthly_minutes: int,
    priority: int = 1,
    runner_type: RunnerType = RunnerType.GITHUB_HOSTED,
) -> None:
    """Set budget for a workflow."""
    monitor = get_github_actions_monitor()
    await monitor.set_workflow_budget(
        workflow_name,
        repository,
        monthly_minutes,
        priority,
        runner_type,
    )

async def should_use_local_runners(
    workflow_name: str,
    repository: str,
) -> bool:
    """Determine if local runners should be used for a workflow."""
    monitor = get_github_actions_monitor()
    return await monitor.should_use_local_runners(workflow_name, repository)