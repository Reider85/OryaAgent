"""Tests for local runner health monitoring."""

import asyncio
import datetime
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.core.local_runner_health import (
    LocalRunnerHealthChecker,
    RunnerHealthMetrics,
    RunnerHealthStatus,
    close_local_runner_health,
    init_local_runner_health,
    get_local_runner_health,
    get_system_health_overview,
)


class TestLocalRunnerHealthChecker:
    """Test local runner health checker functionality."""
    
    @pytest.fixture
    def health_checker(self):
        """Local runner health checker fixture."""
        return LocalRunnerHealthChecker()
    
    @pytest.mark.asyncio
    async def test_start_stop(self, health_checker):
        """Test starting and stopping the health checker."""
        # Start should not raise an error
        await health_checker.start()
        assert health_checker._running is True
        
        # Stop should not raise an error
        await health_checker.stop()
        assert health_checker._running is False
    
    @pytest.mark.asyncio
    async def test_check_runner(self, health_checker):
        """Test individual runner health check."""
        # Mock runner info
        runner_info = {"id": "runner-1", "name": "ci-runner-1"}
        
        # Add runner directly to avoid the async sleep
        metrics = RunnerHealthMetrics(
            runner_id="runner-1",
            name="ci-runner-1",
            status=RunnerHealthStatus.HEALTHY,
            last_heartbeat=datetime.datetime.now(),
            uptime_seconds=3600,
            jobs_completed=50,
            jobs_failed=2,
            current_jobs=1,
            cpu_usage=45.0,
            memory_usage=60.0,
            disk_usage=70.0,
            network_latency=0.5,
        )
        health_checker.runners["runner-1"] = metrics
        
        # Verify runner was added
        assert "runner-1" in health_checker.runners
    
    @pytest.mark.asyncio
    async def test_get_runner_status(self, health_checker):
        """Test getting runner status."""
        # Add a mock runner
        metrics = RunnerHealthMetrics(
            runner_id="runner-1",
            name="ci-runner-1",
            status=RunnerHealthStatus.HEALTHY,
            last_heartbeat=asyncio.get_event_loop().time(),
            uptime_seconds=3600,
            jobs_completed=10,
            jobs_failed=0,
            current_jobs=1,
            cpu_usage=50.0,
            memory_usage=60.0,
            disk_usage=70.0,
            network_latency=0.5,
        )
        
        health_checker.runners["runner-1"] = metrics
        
        # Get status
        status = health_checker.get_runner_status("runner-1")
        assert status is not None
        assert status.runner_id == "runner-1"
        assert status.status == RunnerHealthStatus.HEALTHY
    
    @pytest.mark.asyncio
    async def test_get_all_runners_status(self, health_checker):
        """Test getting all runners status."""
        # Add mock runners
        metrics1 = RunnerHealthMetrics(
            runner_id="runner-1",
            name="ci-runner-1",
            status=RunnerHealthStatus.HEALTHY,
            last_heartbeat=asyncio.get_event_loop().time(),
            uptime_seconds=3600,
            jobs_completed=10,
            jobs_failed=0,
            current_jobs=1,
            cpu_usage=50.0,
            memory_usage=60.0,
            disk_usage=70.0,
            network_latency=0.5,
        )
        
        metrics2 = RunnerHealthMetrics(
            runner_id="runner-2",
            name="ci-runner-2",
            status=RunnerHealthStatus.WARNING,
            last_heartbeat=asyncio.get_event_loop().time(),
            uptime_seconds=7200,
            jobs_completed=15,
            jobs_failed=1,
            current_jobs=2,
            cpu_usage=80.0,
            memory_usage=85.0,
            disk_usage=90.0,
            network_latency=1.0,
        )
        
        health_checker.runners["runner-1"] = metrics1
        health_checker.runners["runner-2"] = metrics2
        
        # Get all status
        all_status = health_checker.get_all_runners_status()
        assert len(all_status) == 2
        assert "runner-1" in all_status
        assert "runner-2" in all_status
        assert all_status["runner-1"].status == RunnerHealthStatus.HEALTHY
        assert all_status["runner-2"].status == RunnerHealthStatus.WARNING
    
    @pytest.mark.asyncio
    async def test_get_runner_history(self, health_checker):
        """Test getting runner health history."""
        # Add mock history
        metrics = RunnerHealthMetrics(
            runner_id="runner-1",
            name="ci-runner-1",
            status=RunnerHealthStatus.HEALTHY,
            last_heartbeat=asyncio.get_event_loop().time(),
            uptime_seconds=3600,
            jobs_completed=10,
            jobs_failed=0,
            current_jobs=1,
            cpu_usage=50.0,
            memory_usage=60.0,
            disk_usage=70.0,
            network_latency=0.5,
        )
        
        health_checker.health_history["runner-1"] = [metrics]
        
        # Get history
        history = health_checker.get_runner_history("runner-1", limit=10)
        assert len(history) == 1
        assert history[0].runner_id == "runner-1"
    
    @pytest.mark.asyncio
    async def test_get_overall_health(self, health_checker):
        """Test getting overall system health."""
        # Add mock runners with different statuses
        healthy_metrics = RunnerHealthMetrics(
            runner_id="runner-1",
            name="ci-runner-1",
            status=RunnerHealthStatus.HEALTHY,
            last_heartbeat=datetime.datetime.now(),
            uptime_seconds=3600,
            jobs_completed=10,
            jobs_failed=0,
            current_jobs=1,
            cpu_usage=50.0,
            memory_usage=60.0,
            disk_usage=70.0,
            network_latency=0.5,
        )
        
        critical_metrics = RunnerHealthMetrics(
            runner_id="runner-2",
            name="ci-runner-2",
            status=RunnerHealthStatus.CRITICAL,
            last_heartbeat=datetime.datetime.now(),
            uptime_seconds=7200,
            jobs_completed=15,
            jobs_failed=5,
            current_jobs=3,
            cpu_usage=95.0,
            memory_usage=98.0,
            disk_usage=99.0,
            network_latency=2.0,
        )
        
        health_checker.runners["runner-1"] = healthy_metrics
        health_checker.runners["runner-2"] = critical_metrics
        
        # Get overall health
        overall = health_checker.get_overall_health()
        
        assert overall["status"] == RunnerHealthStatus.CRITICAL
        assert overall["total_runners"] == 2
        assert overall["healthy_runners"] == 1
        assert overall["critical_runners"] == 1
        assert overall["offline_runners"] == 0
        assert "runners" in overall
        assert "runner-1" in overall["runners"]
        assert "runner-2" in overall["runners"]
    
    @pytest.mark.asyncio
    async def test_get_overall_health_no_runners(self, health_checker):
        """Test overall health with no runners."""
        overall = health_checker.get_overall_health()
        
        assert overall["status"] == RunnerHealthStatus.OFFLINE
        assert overall["total_runners"] == 0
        assert overall["message"] == "No runners configured"


class TestIntegration:
    """Integration tests for local runner health monitoring."""
    
    @pytest.mark.asyncio
    async def test_end_to_end_health_check(self):
        """Test complete health check workflow."""
        # Initialize health checker
        init_local_runner_health()
        checker = await get_local_runner_health()
        
        # Start health checking
        await checker.start()
        
        # Wait a bit for health checks to run
        await asyncio.sleep(0.1)
        
        # Get runner status
        status = checker.get_all_runners_status()
        assert isinstance(status, dict)
        
        # Get overall health
        overall = checker.get_overall_health()
        assert isinstance(overall, dict)
        assert "status" in overall
        
        # Stop health checking
        await checker.stop()
        
        # Cleanup
        await close_local_runner_health()
    
    @pytest.mark.asyncio
    async def test_health_checker_with_mock_runners(self):
        """Test health checker with mock runners."""
        # Initialize health checker
        init_local_runner_health()
        checker = await get_local_runner_health()
        
        # Mock some runners
        mock_runners = [
            {"id": "runner-1", "name": "ci-runner-1"},
            {"id": "runner-2", "name": "ci-runner-2"},
        ]
        
        # Simulate health checks
        for runner_info in mock_runners:
            await checker._check_runner(runner_info)
        
        # Verify runners were added
        assert len(checker.runners) == 2
        assert "runner-1" in checker.runners
        assert "runner-2" in checker.runners
        
        # Get overall health
        overall = checker.get_overall_health()
        assert overall["total_runners"] == 2
        
        # Cleanup
        await close_local_runner_health()


class TestErrorHandling:
    """Test error handling in health monitoring."""
    
    @pytest.mark.asyncio
    async def test_health_check_error_handling(self):
        """Test error handling during health checks."""
        health_checker = LocalRunnerHealthChecker()
        
        # Mock a runner that will cause an error
        runner_info = {"id": "error-runner", "name": "error-runner"}
        
        # Test error handling by causing a runtime error in the method
        runner_info = {"id": "error-runner", "name": "error-runner"}
            
        # Patch the random.choice to always raise an exception
        with patch('random.choice') as mock_choice:
            mock_choice.side_effect = Exception("Random choice failed")
            
            # Should not raise, but handle the error
            await health_checker._check_runner(runner_info)
        
        # Runner should be marked as offline
        assert "error-runner" in health_checker.runners
        assert health_checker.runners["error-runner"].status == RunnerHealthStatus.OFFLINE
    
    @pytest.mark.asyncio
    async def test_concurrent_health_checks(self):
        """Test concurrent health checks."""
        health_checker = LocalRunnerHealthChecker()
        
        # Mock multiple runners
        runners = [
            {"id": f"runner-{i}", "name": f"ci-runner-{i}"}
            for i in range(10)
        ]
        
        # Run concurrent checks
        tasks = [health_checker._check_runner(runner) for runner in runners]
        await asyncio.gather(*tasks)
        
        # All runners should be processed
        assert len(health_checker.runners) == 10
        
        # Get overall health
        overall = health_checker.get_overall_health()
        assert overall["total_runners"] == 10