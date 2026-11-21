#!/usr/bin/env python3

import asyncio
import os
import sys
from unittest.mock import AsyncMock, Mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__)))

from app.core.workflow.tri_model import TriModelPipeline


async def test_tri_model_pipeline_basic():
    """Test basic TriModelPipeline functionality."""
    print("Starting basic pipeline test...")

    try:
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

        print("Pipeline created successfully")

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

        print("Starting turn execution...")
        result = await pipeline.execute_turn(
            session_state=session_state, tools=tools, task=task
        )

        print("Turn execution completed")

        assert result is not None
        assert result.plan is not None
        assert result.execution_result is not None
        assert result.verdict is not None
        assert result.total_duration_ms > 0

        print("SUCCESS: TriModelPipeline basic test passed")
        return True

    except Exception as e:
        print(f"FAILED: Test failed with error: {e}")
        import traceback

        traceback.print_exc()
        return False


if __name__ == "__main__":
    success = asyncio.run(test_tri_model_pipeline_basic())
    print(f"Test result: {'PASS' if success else 'FAIL'}")
    sys.exit(0 if success else 1)
