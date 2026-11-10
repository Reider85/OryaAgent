"""Health monitoring system for local GitHub Actions runners.

This module provides comprehensive health checking for local runner infrastructure
including runner availability, performance metrics, and system status monitoring.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, UTC
from typing import Any, Dict, List, Optional

from app.core.config import get_settings

__all__ = [
    "LocalRunnerHealthChecker",
    "RunnerHealthStatus",
    "RunnerHealthMetrics",
    "init_local_runner_health",
    "get_local_runner_health",
    "close_local_runner_health",
]

logger = logging.getLogger(__name__)

@dataclass
class RunnerHealthMetrics:
    """Health metrics for a local runner."""
    
    runner_id: str
    name: str
    status: str
    last_heartbeat: datetime
    uptime_seconds: float
    jobs_completed: int
    jobs_failed: int
    current_jobs: int
    cpu_usage: float
    memory_usage: float
    disk_usage: float
    network_latency: float
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "runner_id": self.runner_id,
            "name": self.name,
            "status": self.status,
            "last_heartbeat": self.last_heartbeat.isoformat(),
            "uptime_seconds": self.uptime_seconds,
            "jobs_completed": self.jobs_completed,
            "jobs_failed": self.jobs_failed,
            "current_jobs": self.current_jobs,
            "cpu_usage": self.cpu_usage,
            "memory_usage": self.memory_usage,
            "disk_usage": self.disk_usage,
            "network_latency": self.network_latency,
        }

class RunnerHealthStatus:
    """Health status enumeration for local runners."""
    
    HEALTHY = "healthy"
    WARNING = "warning"
    CRITICAL = "critical"
    OFFLINE = "offline"
    MAINTENANCE = "maintenance"

class LocalRunnerHealthChecker:
    """Health checker for local GitHub Actions runners."""
    
    def __init__(self) -> None:
        self.runners: Dict[str, RunnerHealthMetrics] = {}
        self.health_history: Dict[str, List[RunnerHealthMetrics]] = defaultdict(list)
        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._settings = get_settings()
        
    async def start(self) -> None:
        """Start the health checker."""
        if self._running:
            return
        
        self._running = True
        self._task = asyncio.create_task(self._health_check_loop())
        logger.info("Local runner health checker started")
    
    async def stop(self) -> None:
        """Stop the health checker."""
        if not self._running:
            return
        
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("Local runner health checker stopped")
    
    async def _health_check_loop(self) -> None:
        """Main health check loop."""
        while self._running:
            try:
                await self._check_all_runners()
                await asyncio.sleep(self._settings.github_actions_health_interval)
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error("Health check error: %s", exc)
                await asyncio.sleep(self._settings.github_actions_health_interval)
    
    async def _check_all_runners(self) -> None:
        """Check health of all configured runners."""
        settings = get_settings()
        
        # In a real implementation, this would query actual runner APIs
        # For now, we'll simulate health checks
        mock_runners = [
            {"id": "runner-1", "name": "ci-runner-1"},
            {"id": "runner-2", "name": "ci-runner-2"},
            {"id": "runner-3", "name": "build-runner-1"},
        ]
        
        for runner_info in mock_runners:
            await self._check_runner(runner_info)
    
    async def _check_runner(self, runner_info: Dict[str, str]) -> None:
        """Check health of a specific runner."""
        runner_id = runner_info["id"]
        runner_name = runner_info["name"]
        
        try:
            # Simulate health check
            await asyncio.sleep(0.1)  # Simulate network delay
            
            # Generate mock metrics
            current_time = datetime.now()
            uptime = time.time() - (current_time.timestamp() - 3600)  # 1 hour uptime
            
            # Simulate varying health states
            import random
            status = random.choice([
                RunnerHealthStatus.HEALTHY,
                RunnerHealthStatus.HEALTHY,
                RunnerHealthStatus.HEALTHY,
                RunnerHealthStatus.WARNING,
                RunnerHealthStatus.CRITICAL,
            ])
            
            metrics = RunnerHealthMetrics(
                runner_id=runner_id,
                name=runner_name,
                status=status,
                last_heartbeat=current_time,
                uptime_seconds=uptime,
                jobs_completed=random.randint(10, 100),
                jobs_failed=random.randint(0, 5),
                current_jobs=random.randint(0, 3),
                cpu_usage=random.uniform(10, 80),
                memory_usage=random.uniform(20, 70),
                disk_usage=random.uniform(30, 85),
                network_latency=random.uniform(0.1, 2.0),
            )
            
            # Update runner metrics
            self.runners[runner_id] = metrics
            
            # Add to health history
            self.health_history[runner_id].append(metrics)
            
            # Keep only last 100 entries
            if len(self.health_history[runner_id]) > 100:
                self.health_history[runner_id] = self.health_history[runner_id][-100:]
            
            # Log status changes
            if runner_id not in self.runners or self.runners[runner_id].status != status:
                logger.info("Runner %s status changed to %s", runner_id, status)
            
        except Exception as exc:
            logger.error("Health check failed for runner %s: %s", runner_id, exc)
            
            # Mark runner as offline
            current_time = datetime.now()
            offline_metrics = RunnerHealthMetrics(
                runner_id=runner_id,
                name=runner_name,
                status=RunnerHealthStatus.OFFLINE,
                last_heartbeat=current_time,
                uptime_seconds=0,
                jobs_completed=0,
                jobs_failed=0,
                current_jobs=0,
                cpu_usage=0,
                memory_usage=0,
                disk_usage=0,
                network_latency=0,
            )
            
            self.runners[runner_id] = offline_metrics
    
    def get_runner_status(self, runner_id: str) -> Optional[RunnerHealthMetrics]:
        """Get current health status for a specific runner."""
        return self.runners.get(runner_id)
    
    def get_all_runners_status(self) -> Dict[str, RunnerHealthMetrics]:
        """Get health status for all runners."""
        return self.runners.copy()
    
    def get_runner_history(self, runner_id: str, limit: int = 50) -> List[RunnerHealthMetrics]:
        """Get health history for a specific runner."""
        history = self.health_history.get(runner_id, [])
        return history[-limit:]
    
    def get_overall_health(self) -> Dict[str, Any]:
        """Get overall system health status."""
        if not self.runners:
            return {
                "status": RunnerHealthStatus.OFFLINE,
                "message": "No runners configured",
                "total_runners": 0,
                "healthy_runners": 0,
                "warning_runners": 0,
                "critical_runners": 0,
                "offline_runners": 0,
            }
        
        total_runners = len(self.runners)
        healthy_runners = sum(1 for r in self.runners.values() if r.status == RunnerHealthStatus.HEALTHY)
        warning_runners = sum(1 for r in self.runners.values() if r.status == RunnerHealthStatus.WARNING)
        critical_runners = sum(1 for r in self.runners.values() if r.status == RunnerHealthStatus.CRITICAL)
        offline_runners = sum(1 for r in self.runners.values() if r.status == RunnerHealthStatus.OFFLINE)
        
        # Determine overall status
        if offline_runners == total_runners:
            overall_status = RunnerHealthStatus.OFFLINE
        elif critical_runners > 0:
            overall_status = RunnerHealthStatus.CRITICAL
        elif warning_runners > 0:
            overall_status = RunnerHealthStatus.WARNING
        else:
            overall_status = RunnerHealthStatus.HEALTHY
        
        return {
            "status": overall_status,
            "message": f"System health: {overall_status}",
            "total_runners": total_runners,
            "healthy_runners": healthy_runners,
            "warning_runners": warning_runners,
            "critical_runners": critical_runners,
            "offline_runners": offline_runners,
            "runners": {rid: metrics.to_dict() for rid, metrics in self.runners.items()},
        }

# Global health checker instance
_local_runner_health: Optional[LocalRunnerHealthChecker] = None

def init_local_runner_health() -> None:
    """Initialize the local runner health checker."""
    global _local_runner_health
    
    if _local_runner_health is not None:
        return
    
    _local_runner_health = LocalRunnerHealthChecker()
    logger.info("Local runner health checker initialized")

async def get_local_runner_health() -> LocalRunnerHealthChecker:
    """Get the local runner health checker instance."""
    if _local_runner_health is None:
        raise RuntimeError("Local runner health checker not initialized")
    return _local_runner_health

async def close_local_runner_health() -> None:
    """Close the local runner health checker."""
    global _local_runner_health
    
    if _local_runner_health is not None:
        await _local_runner_health.stop()
        _local_runner_health = None
        logger.info("Local runner health checker closed")

# Convenience functions
async def start_local_runner_health() -> None:
    """Start the local runner health checker."""
    checker = await get_local_runner_health()
    await checker.start()

async def stop_local_runner_health() -> None:
    """Stop the local runner health checker."""
    checker = await get_local_runner_health()
    await checker.stop()

async def get_runner_health_status(runner_id: str) -> Optional[RunnerHealthMetrics]:
    """Get health status for a specific runner."""
    checker = await get_local_runner_health()
    return checker.get_runner_status(runner_id)

async def get_all_runners_health_status() -> Dict[str, RunnerHealthMetrics]:
    """Get health status for all runners."""
    checker = await get_local_runner_health()
    return checker.get_all_runners_status()

async def get_system_health_overview() -> Dict[str, Any]:
    """Get overall system health status."""
    checker = await get_local_runner_health()
    return checker.get_overall_health()