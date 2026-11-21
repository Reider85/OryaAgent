"""Hooks audit log page (B-20).

Provides a comprehensive interface for viewing executed hooks and their execution history.
"""

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

router = APIRouter(prefix="/ui/hooks", tags=["hooks-ui"])

templates = Jinja2Templates(directory="app/web/templates")


@router.get("/", response_class=HTMLResponse)
async def hooks_page(request: Request):
    """Hooks audit log main page (B-20).

    Displays a comprehensive view of hook executions with filtering and statistics.
    """
    return templates.TemplateResponse(
        "hooks/hooks.html",
        {
            "request": request,
            "title": "Hooks Audit Log",
            "description": "Monitor and analyze hook execution history and performance",
        },
    )


@router.get("/execution-log", response_class=HTMLResponse)
async def hooks_execution_log(request: Request):
    """Hooks execution log page (B-20).

    Detailed view of hook execution history with real-time updates.
    """
    return templates.TemplateResponse(
        "hooks/execution-log.html",
        {
            "request": request,
            "title": "Hooks Execution Log",
            "description": "Detailed hook execution history with filtering and search",
        },
    )


@router.get("/detail/{hook_name}", response_class=HTMLResponse)
async def hooks_detail(request: Request, hook_name: str):
    """Hook detail page (B-20).

    Detailed view of a specific hook's execution history and statistics.
    """
    return templates.TemplateResponse(
        "hooks/detail.html",
        {
            "request": request,
            "title": f"Hook: {hook_name}",
            "description": f"Execution history and statistics for hook '{hook_name}'",
            "hook_name": hook_name,
        },
    )


@router.get("/statistics", response_class=HTMLResponse)
async def hooks_statistics(request: Request):
    """Hooks statistics page (B-20).

    Dashboard view of hook execution statistics and performance metrics.
    """
    return templates.TemplateResponse(
        "hooks/statistics.html",
        {
            "request": request,
            "title": "Hooks Statistics",
            "description": "Comprehensive statistics and performance metrics for hooks",
        },
    )
