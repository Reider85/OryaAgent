"""GitHub Actions monitoring and hybrid mode API endpoints."""

from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from app.core.config import get_settings
from app.core.github_actions import (
    GitHubActionsBudget,
    GitHubActionsUsage,
    RunnerType,
    get_github_actions_monitor,
    get_workflow_budget,
    get_workflow_usage,
    set_workflow_budget,
    should_use_local_runners,
)
from app.core.hybrid_runner_router import (
    HybridRunnerRouter,
    RunnerSelection,
    get_hybrid_runner_router,
    get_runner_selection,
)

router = APIRouter(tags=["github-actions"])

class WorkflowBudgetRequest(BaseModel):
    """Request to set workflow budget."""
    monthly_minutes: int
    priority: int = 1
    runner_type: str = "github-hosted"

class WorkflowUsageResponse(BaseModel):
    """Response containing workflow usage data."""
    workflow_name: str
    repository: str
    minutes_used: int
    last_updated: str
    budget: dict[str, Any]
    should_use_local: bool

class RunnerSelectionResponse(BaseModel):
    """Response containing runner selection."""
    workflow_name: str
    repository: str
    runner_type: str
    reason: str
    usage: dict[str, Any]
    budget: dict[str, Any]

@router.get("/api/github/actions/usage")
async def get_github_actions_usage(
    workflow_name: str = Query(..., description="Name of the workflow"),
    repository: str = Query("default", description="Repository name"),
) -> WorkflowUsageResponse:
    """Get current usage for a GitHub Actions workflow."""
    try:
        monitor = get_github_actions_monitor()
        usage = await monitor.get_workflow_usage(workflow_name, repository)
        budget = await monitor.get_workflow_budget(workflow_name, repository)
        should_local = await should_use_local_runners(workflow_name, repository)
        
        return WorkflowUsageResponse(
            workflow_name=usage.workflow_name,
            repository=usage.repository,
            minutes_used=usage.minutes_used,
            last_updated=usage.last_updated.isoformat(),
            budget=budget,
            should_use_local=should_local,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/api/github/actions/budget")
async def get_github_actions_budget(
    workflow_name: str = Query(..., description="Name of the workflow"),
    repository: str = Query("default", description="Repository name"),
) -> dict[str, Any]:
    """Get budget for a GitHub Actions workflow."""
    try:
        budget = await get_workflow_budget(workflow_name, repository)
        return budget
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/api/github/actions/budget")
async def set_github_actions_budget(
    request: WorkflowBudgetRequest,
    workflow_name: str = Query(..., description="Name of the workflow"),
    repository: str = Query("default", description="Repository name"),
) -> dict[str, Any]:
    """Set budget for a GitHub Actions workflow."""
    try:
        runner_type = RunnerType(request.runner_type)
        await set_workflow_budget(
            workflow_name,
            repository,
            request.monthly_minutes,
            request.priority,
            runner_type,
        )
        
        return {"status": "success", "message": "Budget updated"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/api/github/actions/runner-selection")
async def get_runner_selection_endpoint(
    workflow_name: str = Query(..., description="Name of the workflow"),
    repository: str = Query("default", description="Repository name"),
) -> RunnerSelectionResponse:
    """Get recommended runner type for a workflow."""
    try:
        selection = await get_runner_selection(workflow_name, repository)
        
        return RunnerSelectionResponse(
            workflow_name=selection.workflow_name,
            repository=selection.repository,
            runner_type=selection.runner_type.value,
            reason=selection.reason,
            usage=selection.usage,
            budget=selection.budget,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/api/github/actions/all-selections")
async def get_all_runner_selections() -> dict[str, RunnerSelectionResponse]:
    """Get runner selections for all configured workflows."""
    try:
        router = get_hybrid_runner_router()
        selections = await router.get_runner_selections()
        
        response = {}
        for key, selection in selections.items():
            response[key] = RunnerSelectionResponse(
                workflow_name=selection.workflow_name,
                repository=selection.repository,
                runner_type=selection.runner_type.value,
                reason=selection.reason,
                usage=selection.usage,
                budget=selection.budget,
            )
        
        return response
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/api/github/actions/optimize")
async def optimize_runner_allocation() -> dict[str, Any]:
    """Optimize runner allocation across all workflows."""
    try:
        router = get_hybrid_runner_router()
        selections = await router.optimize_runner_allocation()
        
        return {
            "status": "success",
            "selections": {
                key: {
                    "workflow_name": sel.workflow_name,
                    "repository": sel.repository,
                    "runner_type": sel.runner_type.value,
                    "reason": sel.reason,
                }
                for key, sel in selections.items()
            }
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/api/github/actions/status")
async def get_github_actions_status() -> dict[str, Any]:
    """Get overall GitHub Actions hybrid mode status."""
    try:
        settings = get_settings()
        monitor = get_github_actions_monitor()
        
        # Get overall usage
        total_usage = 0
        total_budget = 0
        
        if hasattr(settings, 'github_actions_workflows'):
            for workflow_config in settings.github_actions_workflows:
                workflow_name = workflow_config.get('name')
                repository = workflow_config.get('repository', 'default')
                
                if workflow_name:
                    usage = await monitor.get_workflow_usage(workflow_name, repository)
                    budget = await monitor.get_workflow_budget(workflow_name, repository)
                    total_usage += usage.minutes_used
                    total_budget += budget.monthly_minutes
        
        usage_ratio = total_usage / total_budget if total_budget > 0 else 0
        
        return {
            "enabled": settings.github_actions_enabled,
            "local_runners_enabled": settings.local_runners_enabled,
            "total_minutes_used": total_usage,
            "total_minutes_budget": total_budget,
            "usage_ratio": usage_ratio,
            "switch_threshold": settings.github_actions_switch_threshold,
            "health_interval": settings.github_actions_health_interval,
            "should_switch_to_local": usage_ratio >= settings.github_actions_switch_threshold,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))