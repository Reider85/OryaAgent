"""Tests for GitHub Actions hybrid mode functionality."""

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.core.config import Settings
from app.core.github_actions import (
    GitHubActionsBudget,
    GitHubActionsCostStore,
    GitHubActionsMonitor,
    GitHubActionsUsage,
    RunnerType,
    init_github_actions_monitor,
    get_github_actions_monitor,
    close_github_actions_monitor,
    record_workflow_minutes,
    get_workflow_usage,
    get_workflow_budget,
    set_workflow_budget,
    should_use_local_runners,
)
from app.core.hybrid_runner_router import (
    HybridRunnerRouter,
    RunnerSelection,
    get_hybrid_runner_router,
    select_runner_type,
    get_runner_selection,
)


class TestGitHubActionsMonitor:
    """Test GitHub Actions monitoring functionality."""
    
    @pytest.fixture
    def mock_redis(self):
        """Mock Redis client."""
        mock = AsyncMock()
        mock.incrbyfloat = AsyncMock(return_value=100.0)
        mock.expire = AsyncMock()
        mock.get = AsyncMock(return_value="50")
        mock.set = AsyncMock()
        return mock
    
    @pytest.fixture
    def cost_store(self, mock_redis):
        """GitHub Actions cost store fixture."""
        return GitHubActionsCostStore(mock_redis)
    
    @pytest.fixture
    def monitor(self, cost_store):
        """GitHub Actions monitor fixture."""
        return GitHubActionsMonitor(cost_store)
    
    @pytest.mark.asyncio
    async def test_record_workflow_minutes(self, monitor, mock_redis):
        """Test recording workflow minutes."""
        await monitor.cost_store.record_usage("ci", "my-repo", 30)
        
        # Verify Redis calls
        mock_redis.incrby.assert_called_once()
        mock_redis.expire.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_get_workflow_usage(self, monitor, mock_redis):
        """Test getting workflow usage."""
        mock_redis.get.side_effect = ["10", "20", None]
        
        usage = await monitor.cost_store.get_usage("ci", "my-repo", days=3)
        
        assert usage.workflow_name == "ci"
        assert usage.repository == "my-repo"
        assert usage.minutes_used == 30
        assert usage.last_updated is not None
    
    @pytest.mark.asyncio
    async def test_get_workflow_budget_default(self, monitor):
        """Test getting default workflow budget."""
        budget = await monitor.get_workflow_budget("ci", "my-repo")
        
        assert budget.workflow_name == "ci"
        assert budget.repository == "my-repo"
        assert budget.monthly_minutes == 2000
        assert budget.priority == 1
        assert budget.runner_type == RunnerType.GITHUB_HOSTED
    
    @pytest.mark.asyncio
    async def test_should_use_local_runners_exceeded(self, monitor):
        """Test local runner selection when budget is exceeded."""
        # Mock usage that exceeds budget
        with patch.object(monitor, 'get_workflow_usage') as mock_usage:
            mock_usage.return_value = GitHubActionsUsage(
                workflow_name="ci",
                repository="my-repo",
                minutes_used=2500,  # Exceeds default 2000
                last_updated=asyncio.get_event_loop().time(),
            )
            
            # Mock local runner availability
            with patch.object(monitor, '_check_local_runner_health') as mock_health:
                mock_health.return_value = True
                
                should_use = await monitor.should_use_local_runners("ci", "my-repo")
                assert should_use is True
    
    @pytest.mark.asyncio
    async def test_should_use_local_runners_threshold(self, monitor):
        """Test local runner selection when approaching threshold."""
        # Mock usage at threshold
        with patch.object(monitor, 'get_workflow_usage') as mock_usage:
            mock_usage.return_value = GitHubActionsUsage(
                workflow_name="ci",
                repository="my-repo",
                minutes_used=1800,  # 90% of 2000
                last_updated=asyncio.get_event_loop().time(),
            )
            
            # Mock local runner availability
            with patch.object(monitor, '_check_local_runner_health') as mock_health:
                mock_health.return_value = True
                
                should_use = await monitor.should_use_local_runners("ci", "my-repo")
                assert should_use is True


class TestHybridRunnerRouter:
    """Test hybrid runner router functionality."""
    
    @pytest.fixture
    def mock_monitor(self):
        """Mock GitHub Actions monitor."""
        monitor = AsyncMock()
        monitor.get_workflow_usage = AsyncMock()
        monitor.get_workflow_budget = AsyncMock()
        monitor._check_local_runner_health = AsyncMock(return_value=True)
        return monitor
    
    @pytest.fixture
    def router(self, mock_monitor):
        """Hybrid runner router fixture."""
        return HybridRunnerRouter(mock_monitor)
    
    @pytest.mark.asyncio
    async def test_select_runner_default(self, router, mock_monitor):
        """Test default runner selection."""
        # Mock usage and budget
        usage = GitHubActionsUsage(
            workflow_name="ci",
            repository="my-repo",
            minutes_used=100,
            last_updated=asyncio.get_event_loop().time(),
        )
        
        budget = GitHubActionsBudget(
            workflow_name="ci",
            repository="my-repo",
            monthly_minutes=2000,
            priority=1,
            runner_type=RunnerType.GITHUB_HOSTED,
        )
        
        mock_monitor.get_workflow_usage.return_value = usage
        mock_monitor.get_workflow_budget.return_value = budget
        mock_monitor._check_local_runner_health = AsyncMock(return_value=True)
        
        selection = await router.select_runner("ci", "my-repo")
        
        assert selection.workflow_name == "ci"
        assert selection.repository == "my-repo"
        assert selection.runner_type == RunnerType.GITHUB_HOSTED
        assert selection.reason == "default"
    
    @pytest.mark.asyncio
    async def test_select_runner_budget_exceeded(self, router, mock_monitor):
        """Test runner selection when budget is exceeded."""
        # Mock usage that exceeds budget
        usage = GitHubActionsUsage(
            workflow_name="ci",
            repository="my-repo",
            minutes_used=2500,  # Exceeds budget
            last_updated=asyncio.get_event_loop().time(),
        )
        
        budget = GitHubActionsBudget(
            workflow_name="ci",
            repository="my-repo",
            monthly_minutes=2000,
            priority=1,
            runner_type=RunnerType.GITHUB_HOSTED,
        )
        
        mock_monitor.get_workflow_usage.return_value = usage
        mock_monitor.get_workflow_budget.return_value = budget
        mock_monitor._check_local_runner_health = AsyncMock(return_value=True)
        
        selection = await router.select_runner("ci", "my-repo")
        
        assert selection.runner_type == RunnerType.SELF_HOSTED
        assert selection.reason == "budget_exceeded"
    
    @pytest.mark.asyncio
    async def test_select_runner_high_priority(self, router, mock_monitor):
        """Test runner selection for high priority workflows."""
        # Mock high priority budget
        usage = GitHubActionsUsage(
            workflow_name="critical-ci",
            repository="my-repo",
            minutes_used=1800,  # Approaching threshold
            last_updated=asyncio.get_event_loop().time(),
        )
        
budget = GitHubActionsBudget(
            workflow_name="ci",
            repository="my-repo",
            monthly_minutes=2000,
            priority=2,
            runner_type=RunnerType.GITHUB_HOSTED,
        )
        
        mock_monitor.get_workflow_usage.return_value = usage
        mock_monitor.get_workflow_budget.return_value = budget
        mock_monitor._check_local_runner_health = AsyncMock(return_value=True)
        
        selection = await router.select_runner("critical-ci", "my-repo")
        
        # High priority workflows always use GitHub-hosted
        assert selection.runner_type == RunnerType.GITHUB_HOSTED
        assert selection.reason == "high_priority"
    
    @pytest.mark.asyncio
    async def test_get_all_runner_selections(self, router, mock_monitor):
        """Test getting runner selections for all workflows."""
        # Mock multiple workflows
        workflows = [
            ("ci", "my-repo"),
            ("release", "my-repo"),
            ("nightly", "my-org"),
        ]
        
        mock_monitor.get_workflow_usage.side_effect = [
            GitHubActionsUsage(name, repo, 100, asyncio.get_event_loop().time())
            for name, repo in workflows
        ]
        
        mock_monitor.get_workflow_budget.side_effect = [
            GitHubActionsBudget(name, repo, 2000, 2, RunnerType.GITHUB_HOSTED)
            for name, repo in workflows
        ]
        
        selections = await router.get_runner_selections()
        
        assert len(selections) == 3
        for name, repo in workflows:
            key = f"{repo}:{name}"
            assert key in selections
            assert selections[key].workflow_name == name
            assert selections[key].repository == repo


class TestIntegration:
    """Integration tests for hybrid mode."""
    
    @pytest.mark.asyncio
    async def test_end_to_end_workflow(self):
        """Test complete workflow from recording usage to runner selection."""
        # Initialize monitor
        init_github_actions_monitor(force=True)
        monitor = get_github_actions_monitor()
        
        # Set budget for a workflow
        await set_workflow_budget(
            "ci",
            "my-repo",
            monthly_minutes=1000,
            priority=2,
            runner_type=RunnerType.GITHUB_HOSTED,
        )
        
        # Record some usage
        await record_workflow_minutes("ci", "my-repo", 800)
        
        # Check usage
        usage = await get_workflow_usage("ci", "my-repo")
        assert usage.minutes_used == 800
        
        # Check if we should use local runners
        should_use = await monitor.should_use_local_runners("ci", "my-repo")
        
        # At 800/1000 (80%), we shouldn't switch yet unless threshold is lower
        settings = Settings()
        if settings.github_actions_switch_threshold <= 0.8:
            assert should_use is True
        else:
            assert should_use is False
        
        # Initialize router
        from app.core.hybrid_runner_router import init_hybrid_runner_router
        init_hybrid_runner_router()
        router = get_hybrid_runner_router()
        
        # Get runner selection
        selection = await get_runner_selection("ci", "my-repo")
        assert selection.workflow_name == "ci"
        assert selection.repository == "my-repo"
        
        # Cleanup
        await close_github_actions_monitor()
        from app.core.hybrid_runner_router import close_hybrid_runner_router
        await close_hybrid_runner_router()
    
    @pytest.mark.asyncio
    async def test_budget_optimization(self):
        """Test budget optimization across multiple workflows."""
        # Initialize monitor and router
        init_github_actions_monitor(force=True)
        monitor = get_github_actions_monitor()
        
        # Configure workflows with different priorities
        workflows = [
            ("critical-ci", "my-repo", 2000, 1),  # High priority
            ("regular-ci", "my-repo", 1000, 2),   # Normal priority
            ("nightly", "my-org", 500, 3),        # Low priority
        ]
        
        for name, repo, minutes, priority in workflows:
            await set_workflow_budget(name, repo, minutes, priority, RunnerType.GITHUB_HOSTED)
            await record_workflow_minutes(name, repo, int(minutes * 0.9))  # 90% usage
        
        # Initialize router
        from app.core.hybrid_runner_router import init_hybrid_runner_router
        init_hybrid_runner_router()
        router = get_hybrid_runner_router()
        
        # Optimize allocation
        selections = await router.optimize_runner_allocation()
        
        # Critical workflows should still use GitHub-hosted
        critical_selection = selections["my-repo:critical-ci"]
        assert critical_selection.runner_type == RunnerType.GITHUB_HOSTED
        assert critical_selection.reason == "critical_priority"
        
        # Other workflows might be optimized
        regular_selection = selections["my-repo:regular-ci"]
        assert regular_selection.workflow_name == "regular-ci"
        
        # Cleanup
        await close_github_actions_monitor()
        from app.core.hybrid_runner_router import close_hybrid_runner_router
        await close_hybrid_runner_router()


class TestConfiguration:
    """Test configuration handling for hybrid mode."""
    
    def test_settings_defaults(self):
        """Test default settings for GitHub Actions hybrid mode."""
        settings = Settings()
        
        # Check default values
        assert settings.github_actions_enabled is False
        assert settings.local_runners_enabled is False
        assert settings.github_actions_default_minutes == 2000
        assert settings.github_actions_switch_threshold == 0.9
        assert settings.github_actions_health_interval == 30
        assert settings.github_actions_workflows == []
    
    def test_settings_override(self):
        """Test settings override via environment variables."""
        with patch.dict('os.environ', {
            'ORYA_GITHUB_ACTIONS_ENABLED': 'true',
            'ORYA_LOCAL_RUNNERS_ENABLED': 'true',
            'ORYA_GITHUB_ACTIONS_DEFAULT_MINUTES': '5000',
            'ORYA_GITHUB_ACTIONS_SWITCH_THRESHOLD': '0.8',
        }):
            settings = Settings()
            
            assert settings.github_actions_enabled is True
            assert settings.local_runners_enabled is True
            assert settings.github_actions_default_minutes == 5000
            assert settings.github_actions_switch_threshold == 0.8
    
    def test_yaml_configuration(self):
        """Test YAML configuration fallback."""
        # This would test the YAML configuration loading
        # For now, we just verify the field exists
        assert hasattr(Settings(), 'github_actions_enabled')
        assert hasattr(Settings(), 'local_runners_enabled')
        assert hasattr(Settings(), 'github_actions_workflows')