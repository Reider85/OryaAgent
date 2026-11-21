#!/usr/bin/env python3

import asyncio
import os
import sys
from unittest.mock import AsyncMock, Mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__)))

from app.core.workflow.prompts import PlannerPrompt, TesterPrompt
from app.core.workflow.tri_model import Plan, TriModelPipeline, Verdict


def test_plan_creation():
    """Test Plan dataclass creation."""
    plan = Plan(
        steps=["Step 1", "Step 2"],
        criteria=["Criterion 1", "Criterion 2"],
        prefetch_hints=["Hint 1", "Hint 2"],
        tier="small",
    )

    assert len(plan.steps) == 2
    assert len(plan.criteria) == 2
    assert len(plan.prefetch_hints) == 2
    assert plan.tier == "small"
    assert plan.cacheable_prefix == ""
    assert plan.dynamic_suffix == ""

    print("SUCCESS: Plan creation test passed")
    return True


def test_verdict_creation():
    """Test Verdict dataclass creation."""
    verdict = Verdict(
        verdict="pass", message="Test passed", confidence=0.95, failed_criteria=[]
    )

    assert verdict.verdict == "pass"
    assert verdict.message == "Test passed"
    assert verdict.confidence == 0.95
    assert len(verdict.failed_criteria) == 0

    print("SUCCESS: Verdict creation test passed")
    return True


async def test_tri_model_pipeline_basic():
    """Test basic TriModelPipeline functionality."""
    # Create mock models
    mock_planner = Mock()
    mock_executor = Mock()
    mock_tester = Mock()

    # Mock model responses
    mock_planner.generate = AsyncMock(return_value="Plan generated")
    mock_executor.generate = AsyncMock(return_value="Execution completed")
    mock_tester.generate = AsyncMock(return_value="Test passed")

    # Create pipeline
    pipeline = TriModelPipeline(
        planner_model=mock_planner,
        executor_model=mock_executor,
        tester_model=mock_tester,
    )

    # Test turn execution
    session_state = {
        "session_id": "test_session",
        "current_dir": "/test",
        "files": [],
        "recent_activity": "none",
    }

    tools = [
        Mock(name="read", description="Read files"),
        Mock(name="write", description="Write files"),
    ]
    task = "Create a simple Python function"

    result = await pipeline.execute_turn(
        session_state=session_state, tools=tools, task=task
    )

    assert result is not None
    assert result.plan is not None
    assert result.execution_result is not None
    assert result.verdict is not None
    assert result.total_duration_ms > 0

    print("SUCCESS: TriModelPipeline basic test passed")
    return True


async def test_tri_model_pipeline_replanning():
    """Test TriModelPipeline with replanning."""
    # Create mock models
    mock_planner = Mock()
    mock_executor = Mock()
    mock_tester = Mock()

    # Mock model responses for replanning scenario
    mock_planner.generate = AsyncMock(side_effect=["Initial plan", "Revised plan"])
    mock_executor.generate = AsyncMock(return_value="Execution completed")
    mock_tester.generate = AsyncMock(side_effect=["Test failed", "Test passed"])

    # Create pipeline with replanning
    pipeline = TriModelPipeline(
        planner_model=mock_planner,
        executor_model=mock_executor,
        tester_model=mock_tester,
        max_replans=2,
    )

    # Test turn execution with replanning
    session_state = {
        "session_id": "test_session",
        "current_dir": "/test",
        "files": [],
        "recent_activity": "none",
    }

    tools = [Mock(name="read", description="Read files")]
    task = "Create a Python function with error"

    result = await pipeline.execute_turn(
        session_state=session_state, tools=tools, task=task
    )

    assert result is not None
    assert result.replan_count > 0  # Should have replanned

    print("SUCCESS: TriModelPipeline replanning test passed")
    return True


def test_prompt_building():
    """Test prompt building functionality."""
    # Test planner prompt
    planner_prompt = PlannerPrompt()
    prompt = planner_prompt.build_prompt(
        task="Create a Python function",
        context="Simple utility function",
        available_tools=["read", "write", "edit"],
        session_history=["Created file1.py"],
        max_steps=3,
    )

    assert "Create a Python function" in prompt
    assert "read" in prompt
    assert "write" in prompt
    assert "edit" in prompt
    assert "3" in prompt

    # Test tester prompt
    tester_prompt = TesterPrompt()
    test_prompt = tester_prompt.build_prompt(
        plan={"steps": ["Step 1"], "criteria": ["Criterion 1"]},
        execution_result={"status": "success", "output": "Done"},
        session_context="Test context",
        run_tests=False,
    )

    assert "Step 1" in test_prompt
    assert "Criterion 1" in test_prompt
    assert "success" in test_prompt

    print("SUCCESS: Prompt building test passed")
    return True


async def run_all_tests():
    """Run all tests."""
    print("Running B-25 Tri-Model Pipeline tests...")

    try:
        # Test data models
        test_plan_creation()
        test_verdict_creation()

        # Test prompts
        test_prompt_building()

        # Test pipeline functionality
        await test_tri_model_pipeline_basic()
        await test_tri_model_pipeline_replanning()

        print("\nSUCCESS: All tests passed!")
        return True

    except Exception as e:
        print(f"\nFAILED: Test failed with error: {e}")
        import traceback

        traceback.print_exc()
        return False


if __name__ == "__main__":
    success = asyncio.run(run_all_tests())
    sys.exit(0 if success else 1)
