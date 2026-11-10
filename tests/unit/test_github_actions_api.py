"""Tests for GitHub Actions hybrid mode API endpoints."""

import datetime
import json
import pytest
from fastapi.testclient import TestClient
from unittest.mock import AsyncMock, MagicMock, patch

from app.main import app
from app.core.github_actions import GitHubActionsMonitor
from app.core.hybrid_runner_router import HybridRunnerRouter


class TestGitHubActionsAPI:
    """Test GitHub Actions API endpoints."""
    
    @pytest.fixture
    def client(self):
        """Test client fixture."""
        return TestClient(app)
    
    @pytest.fixture
    def mock_monitor(self):
        """Mock GitHub Actions monitor."""
        monitor = AsyncMock(spec=GitHubActionsMonitor)
        monitor.get_workflow_usage = AsyncMock(return_value=None)
        monitor.get_workflow_budget = AsyncMock(return_value=None)
        monitor.should_use_local_runners = AsyncMock(return_value=False)
        return monitor
    
    @pytest.fixture
    def mock_router(self):
        """Mock hybrid runner router."""
        router = AsyncMock(spec=HybridRunnerRouter)
        router.select_runner = AsyncMock(return_value=None)
        router.get_runner_selections = AsyncMock(return_value={})
        router.optimize_runner_allocation = AsyncMock(return_value={})
        return router
    
    def test_get_github_actions_usage(self, client, mock_monitor):
        """Test getting GitHub Actions usage."""
        # Initialize the monitor globally for this test
        from app.core.github_actions import init_github_actions_monitor, _github_actions_monitor
        init_github_actions_monitor(force=True)
        
        # Set the global monitor directly
        import app.core.github_actions
        app.core.github_actions._github_actions_monitor = mock_monitor
        
        # Set up the monitor with test data
        from datetime import datetime
        mock_monitor.get_workflow_usage.return_value = AsyncMock(
            workflow_name="ci",
            repository="my-repo",
            minutes_used=100,
            last_updated=datetime.now()
        )
        mock_monitor.get_workflow_budget.return_value = {
            "workflow_name": "ci",
            "repository": "my-repo",
            "monthly_minutes": 2000,
            "priority": 1,
            "runner_type": "github-hosted"
        }
        
        response = client.get("/api/github/actions/usage?workflow_name=ci&repository=my-repo")
        
        assert response.status_code == 200
        data = response.json()
        assert "workflow_name" in data
        assert "repository" in data
        assert "minutes_used" in data
        assert "should_use_local" in data
    
    def test_get_github_actions_budget(self, client, mock_monitor):
        """Test getting GitHub Actions budget."""
        with patch('app.api.github_actions.get_github_actions_monitor', return_value=mock_monitor):
            response = client.get("/api/github/actions/budget?workflow_name=ci&repository=my-repo")
            
            assert response.status_code == 200
            data = response.json()
            assert "workflow_name" in data
            assert "repository" in data
            assert "monthly_minutes" in data
    
    def test_set_github_actions_budget(self, client, mock_monitor):
        """Test setting GitHub Actions budget."""
        with patch('app.api.github_actions.get_github_actions_monitor', return_value=mock_monitor):
            budget_data = {
                "monthly_minutes": 3000,
                "priority": 1,
                "runner_type": "github-hosted"
            }
            
            response = client.post(
                "/api/github/actions/budget?workflow_name=ci&repository=my-repo",
                json=budget_data
            )
            
            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "success"
    
    def test_get_runner_selection(self, client, mock_monitor, mock_router):
        """Test getting runner selection."""
        # Initialize the monitor globally for this test
        from app.core.github_actions import init_github_actions_monitor, _github_actions_monitor
        init_github_actions_monitor(force=True)
        
        # Set the global monitor directly
        import app.core.github_actions
        app.core.github_actions._github_actions_monitor = mock_monitor
        
        from app.core.hybrid_runner_router import RunnerType
        
        # Set up the router with test data
        mock_router.select_runner.return_value = AsyncMock(
            workflow_name="ci",
            repository="my-repo",
            runner_type=RunnerType.GITHUB_HOSTED,
            reason="default",
            usage={"workflow_name": "ci", "repository": "my-repo", "minutes_used": 100, "last_updated": "2023-01-01T00:00:00Z"},
            budget={"workflow_name": "ci", "repository": "my-repo", "monthly_minutes": 2000, "priority": 1, "runner_type": "github-hosted"}
        )
        
        with patch('app.core.hybrid_runner_router.get_hybrid_runner_router', return_value=mock_router):
            response = client.get("/api/github/actions/runner-selection?workflow_name=ci&repository=my-repo")
            
            assert response.status_code == 200
            data = response.json()
            assert "workflow_name" in data
            assert "repository" in data
            assert "runner_type" in data
            assert "reason" in data
    
    def test_get_all_runner_selections(self, client, mock_monitor, mock_router):
        """Test getting all runner selections."""
        # Initialize the monitor globally for this test
        from app.core.github_actions import init_github_actions_monitor, _github_actions_monitor
        init_github_actions_monitor(force=True)
        
        # Set the global monitor directly
        import app.core.github_actions
        app.core.github_actions._github_actions_monitor = mock_monitor
        
        # Initialize the hybrid runner router
        from app.core.hybrid_runner_router import init_hybrid_runner_router, _hybrid_runner_router
        init_hybrid_runner_router()
        import app.core.hybrid_runner_router
        app.core.hybrid_runner_router._hybrid_runner_router = mock_router
        
        from app.core.hybrid_runner_router import RunnerSelection, RunnerType, GitHubActionsUsage, GitHubActionsBudget
        
        # Set up the router with test data
        mock_router.get_runner_selections.return_value = {
            "my-repo:ci": RunnerSelection(
                workflow_name="ci",
                repository="my-repo",
                runner_type=RunnerType.GITHUB_HOSTED,
                reason="default",
                usage={
                    "workflow_name": "ci",
                    "repository": "my-repo",
                    "minutes_used": 100,
                    "last_updated": datetime.datetime.now().isoformat()
                },
                budget={
                    "workflow_name": "ci",
                    "repository": "my-repo",
                    "monthly_minutes": 2000,
                    "priority": 1,
                    "runner_type": "github-hosted"
                }
            )
}
        
        response = client.get("/api/github/actions/all-selections")
        
        assert response.status_code == 200
        data = response.json()
        assert "my-repo:ci" in data
        assert isinstance(data, dict)
    
    def test_optimize_runner_allocation(self, client, mock_router):
        """Test optimizing runner allocation."""
        with patch('app.api.github_actions.get_hybrid_runner_router', return_value=mock_router):
            response = client.post("/api/github/actions/optimize")
            
            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "success"
            assert "selections" in data
    
    def test_get_github_actions_status(self, client):
        """Test getting GitHub Actions status."""
        with patch('app.api.github_actions.get_settings') as mock_settings:
            mock_settings.return_value.github_actions_enabled = True
            mock_settings.return_value.local_runners_enabled = True
            mock_settings.return_value.github_actions_switch_threshold = 0.9
            mock_settings.return_value.github_actions_health_interval = 30
            
            response = client.get("/api/github/actions/status")
            
            assert response.status_code == 200
            data = response.json()
            assert "enabled" in data
            assert "local_runners_enabled" in data
            assert "total_minutes_used" in data
            assert "total_minutes_budget" in data
            assert "usage_ratio" in data
            assert "should_switch_to_local" in data
    
    def test_api_error_handling(self, client):
        """Test API error handling."""
        # Test with invalid workflow name
        response = client.get("/api/github/actions/usage?workflow_name=&repository=my-repo")
        assert response.status_code == 422  # Validation error
        
        # Test with missing workflow name
        response = client.get("/api/github/actions/usage?repository=my-repo")
        assert response.status_code == 422  # Validation error


class TestHealthAPI:
    """Test health API endpoints for hybrid mode."""
    
    @pytest.fixture
    def client(self):
        """Test client fixture."""
        return TestClient(app)
    
    @pytest.fixture
    def mock_health_checker(self):
        """Mock local runner health checker."""
        checker = AsyncMock()
        checker.get_overall_health = AsyncMock(return_value={
            "status": "healthy",
            "total_runners": 3,
            "healthy_runners": 3,
            "warning_runners": 0,
            "critical_runners": 0,
            "offline_runners": 0,
        })
        return checker
    
    def test_health_local_runners(self, client, mock_health_checker):
        """Test local runners health endpoint."""
        with patch('app.api.health.get_system_health_overview', return_value=mock_health_checker):
            response = client.get("/health/local-runners")
            
            assert response.status_code == 200
            data = response.json()
            assert "github_actions" in data
            assert "local_runners" in data
            assert "status" in data["local_runners"]
            assert "total_runners" in data["local_runners"]
    
    def test_health_hybrid_mode(self, client):
        """Test hybrid mode health endpoint."""
        with patch('app.api.health.get_hybrid_runner_router') as mock_router:
            mock_router.return_value.get_runner_selections = AsyncMock(return_value={
                "my-repo:ci": {
                    "workflow": "ci",
                    "repository": "my-repo",
                    "runner_type": "github-hosted",
                    "reason": "default"
                }
            })
            
            response = client.get("/health/hybrid-mode")
            
            assert response.status_code == 200
            data = response.json()
            assert "github_actions_enabled" in data
            assert "local_runners_enabled" in data
            assert "total_workflows" in data
            assert "using_local_runners" in data
            assert "switch_threshold" in data
            assert "runner_selections" in data


class TestAPIIntegration:
    """Integration tests for API endpoints."""
    
    @pytest.fixture
    def client(self):
        """Test client fixture."""
        return TestClient(app)
    
    @pytest.mark.asyncio
    async def test_complete_workflow_api(self, client):
        """Test complete workflow through API."""
        # Mock the monitor and router
        with patch('app.api.github_actions.get_github_actions_monitor') as mock_monitor, \
             patch('app.api.github_actions.get_runner_selection') as mock_selection, \
             patch('app.api.github_actions.get_hybrid_runner_router') as mock_router:
            
            # Mock monitor responses
            mock_monitor.return_value.get_workflow_usage = AsyncMock(return_value={
                "workflow_name": "ci",
                "repository": "my-repo",
                "minutes_used": 100,
                "last_updated": "2023-01-01T00:00:00Z"
            })
            
            mock_monitor.return_value.get_workflow_budget = AsyncMock(return_value={
                "workflow_name": "ci",
                "repository": "my-repo",
                "monthly_minutes": 2000,
                "priority": 1,
                "runner_type": "github-hosted"
            })
            
            mock_monitor.return_value.should_use_local_runners = AsyncMock(return_value=False)
            
            # Mock router response
            mock_selection.return_value = {
                "workflow_name": "ci",
                "repository": "my-repo",
                "runner_type": "github-hosted",
                "reason": "default",
                "usage": {
                    "workflow_name": "ci",
                    "repository": "my-repo",
                    "minutes_used": 100,
                    "last_updated": "2023-01-01T00:00:00Z"
                },
                "budget": {
                    "workflow_name": "ci",
                    "repository": "my-repo",
                    "monthly_minutes": 2000,
                    "priority": 1,
                    "runner_type": "github-hosted"
                }
            }
            
            mock_router.return_value.get_runner_selections = AsyncMock(return_value={
                "my-repo:ci": mock_selection.return_value
            })
            
            # Test API calls
            # 1. Get usage
            response = client.get("/api/github/actions/usage?workflow_name=ci&repository=my-repo")
            assert response.status_code == 200
            
            # 2. Get budget
            response = client.get("/api/github/actions/budget?workflow_name=ci&repository=my-repo")
            assert response.status_code == 200
            
            # 3. Set budget
            budget_data = {
                "monthly_minutes": 3000,
                "priority": 1,
                "runner_type": "github-hosted"
            }
            response = client.post(
                "/api/github/actions/budget?workflow_name=ci&repository=my-repo",
                json=budget_data
            )
            assert response.status_code == 200
            
            # 4. Get runner selection
            response = client.get("/api/github/actions/runner-selection?workflow_name=ci&repository=my-repo")
            assert response.status_code == 200
            
            # 5. Get all selections
            response = client.get("/api/github/actions/all-selections")
            assert response.status_code == 200
            
            # 6. Get status
            response = client.get("/api/github/actions/status")
            assert response.status_code == 200
    
    @pytest.mark.asyncio
    async def test_api_error_scenarios(self, client):
        """Test API error scenarios."""
        # Test with non-existent workflow
        response = client.get("/api/github/actions/usage?workflow_name=nonexistent&repository=my-repo")
        # Should handle gracefully (either 200 with empty data or 404)
        assert response.status_code in [200, 404]
        
        # Test with invalid budget data
        budget_data = {
            "monthly_minutes": -100,  # Invalid negative value
            "priority": 1,
            "runner_type": "github-hosted"
        }
        response = client.post(
            "/api/github/actions/budget?workflow_name=ci&repository=my-repo",
            json=budget_data
        )
        assert response.status_code == 422  # Validation error
        
        # Test with invalid runner type
        budget_data = {
            "monthly_minutes": 3000,
            "priority": 1,
            "runner_type": "invalid-runner-type"
        }
        response = client.post(
            "/api/github/actions/budget?workflow_name=ci&repository=my-repo",
            json=budget_data
        )
        assert response.status_code == 422  # Validation error


class TestAPIAuthentication:
    """Test API authentication and authorization."""
    
    @pytest.fixture
    def client(self):
        """Test client fixture."""
        return TestClient(app)
    
    def test_api_access_without_auth(self, client):
        """Test API access without authentication."""
        # These endpoints should be publicly accessible
        endpoints = [
            "/api/github/actions/usage",
            "/api/github/actions/budget",
            "/api/github/actions/runner-selection",
            "/api/github/actions/all-selections",
            "/api/github/actions/optimize",
            "/api/github/actions/status",
            "/health/local-runners",
            "/health/hybrid-mode",
        ]
        
        for endpoint in endpoints:
            response = client.get(endpoint)
            # Most endpoints should be accessible without auth
            # Some might return 422 if required params are missing
            assert response.status_code in [200, 422]