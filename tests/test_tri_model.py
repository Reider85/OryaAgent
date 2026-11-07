"""Tests for Tri-Model Pipeline components."""

import pytest
import asyncio
from unittest.mock import Mock, AsyncMock, patch, MagicMock
from pathlib import Path

from app.core.workflow.tri_model import (
    get_tri_model_pipeline,
    initialize_tri_model_pipeline,
    TriModelPipeline,
    PlanPhase,
    ExecutePhase,
    TestPhase,
    TriModelState,
    PlanResult,
    ExecuteResult,
    TestResult,
)


class TestTriModelState:
    """Test TriModelState functionality."""
    
    def test_state_creation(self):
        """Test state creation."""
        state = TriModelState(
            task="Generate a Python function",
            plan=None,
            execution=None,
            test=None,
            iterations=0,
            max_iterations=3,
            context={"language": "python"},
        )
        
        assert state.task == "Generate a Python function"
        assert state.plan is None
        assert state.execution is None
        assert state.test is None
        assert state.iterations == 0
        assert state.max_iterations == 3
        assert state.context == {"language": "python"}
    
    def test_state_update(self):
        """Test state update."""
        state = TriModelState(
            task="Generate a Python function",
            plan=None,
            execution=None,
            test=None,
            iterations=0,
            max_iterations=3,
        )
        
        # Update with plan
        plan_result = PlanResult(
            plan="def factorial(n):",
            confidence=0.8,
            reasoning="Simple recursive factorial function",
        )
        
        updated_state = state.with_plan(plan_result)
        
        assert updated_state.plan == plan_result
        assert updated_state.iterations == 0
        
        # Update with execution
        execute_result = ExecuteResult(
            code="def factorial(n):\n    if n == 0:\n        return 1\n    return n * factorial(n-1)",
            execution_time=0.1,
            output="",
            success=True,
        )
        
        updated_state = updated_state.with_execution(execute_result)
        
        assert updated_state.execution == execute_result
        assert updated_state.iterations == 0
        
        # Update with test
        test_result = TestResult(
            passed=True,
            test_results=[{"name": "test_factorial", "passed": True}],
            coverage=80,
            execution_time=0.2,
        )
        
        updated_state = updated_state.with_test(test_result)
        
        assert updated_state.test == test_result
        assert updated_state.iterations == 1
    
    def test_state_iteration_increment(self):
        """Test state iteration increment."""
        state = TriModelState(
            task="Generate a Python function",
            iterations=0,
            max_iterations=3,
        )
        
        # Increment iterations
        updated_state = state.increment_iterations()
        
        assert updated_state.iterations == 1
        assert updated_state.max_iterations == 3
        
        # Should not exceed max iterations
        for _ in range(5):
            updated_state = updated_state.increment_iterations()
        
        assert updated_state.iterations == 3  # Should be capped at max_iterations


class TestPlanPhase:
    """Test PlanPhase functionality."""
    
    def test_plan_phase_creation(self):
        """Test plan phase creation."""
        phase = PlanPhase()
        
        assert phase.name == "plan"
        assert phase.max_iterations == 3
        assert phase.timeout == 30
    
    @pytest.mark.asyncio
    async def test_plan_phase_execution(self):
        """Test plan phase execution."""
        phase = PlanPhase()
        
        # Mock LLM
        mock_llm = Mock()
        mock_llm.generate_plan = AsyncMock(return_value=PlanResult(
            plan="def factorial(n):",
            confidence=0.8,
            reasoning="Simple recursive factorial function",
        ))
        
        state = TriModelState(
            task="Generate a Python function to calculate factorial",
            max_iterations=3,
        )
        
        result = await phase.execute(state, mock_llm)
        
        assert result.plan is not None
        assert result.plan.plan == "def factorial(n):"
        assert result.plan.confidence == 0.8
        assert result.plan.reasoning == "Simple recursive factorial function"
        assert result.iterations == 0
        
        mock_llm.generate_plan.assert_called_once_with(state)
    
    @pytest.mark.asyncio
    async def test_plan_phase_with_context(self):
        """Test plan phase execution with context."""
        phase = PlanPhase()
        
        # Mock LLM
        mock_llm = Mock()
        mock_llm.generate_plan = AsyncMock(return_value=PlanResult(
            plan="def factorial(n):",
            confidence=0.9,
            reasoning="Recursive factorial function with context",
        ))
        
        state = TriModelState(
            task="Generate a Python function",
            max_iterations=3,
            context={"language": "python", "style": "functional"},
        )
        
        result = await phase.execute(state, mock_llm)
        
        assert result.plan is not None
        assert result.plan.confidence == 0.9
        assert "context" in mock_llm.generate_plan.call_args[0][0].context
    
    @pytest.mark.asyncio
    async def test_plan_phase_error_handling(self):
        """Test plan phase error handling."""
        phase = PlanPhase()
        
        # Mock LLM to raise error
        mock_llm = Mock()
        mock_llm.generate_plan = AsyncMock(side_effect=Exception("Planning failed"))
        
        state = TriModelState(
            task="Generate a Python function",
            max_iterations=3,
        )
        
        result = await phase.execute(state, mock_llm)
        
        assert result.plan is None
        assert result.iterations == 0
        assert result.error == "Planning failed"
    
    @pytest.mark.asyncio
    async def test_plan_phase_max_iterations(self):
        """Test plan phase with max iterations."""
        phase = PlanPlanPhase()
        
        # Mock LLM
        mock_llm = Mock()
        mock_llm.generate_plan = AsyncMock(return_value=PlanResult(
            plan="def factorial(n):",
            confidence=0.8,
            reasoning="Simple recursive factorial function",
        ))
        
        state = TriModelState(
            task="Generate a Python function",
            iterations=2,  # Already at max iterations - 1
            max_iterations=3,
        )
        
        result = await phase.execute(state, mock_llm)
        
        # Should not execute if at max iterations
        assert result.plan is None
        assert result.iterations == 2
        assert result.error == "Max iterations reached"
        mock_llm.generate_plan.assert_not_called()


class TestExecutePhase:
    """Test ExecutePhase functionality."""
    
    def test_execute_phase_creation(self):
        """Test execute phase creation."""
        phase = ExecutePhase()
        
        assert phase.name == "execute"
        assert phase.timeout == 60
        assert phase.max_output_length = 1000
    
    @pytest.mark.asyncio
    async def test_execute_phase_execution(self):
        """Test execute phase execution."""
        phase = ExecutePhase()
        
        # Mock executor
        mock_executor = Mock()
        mock_executor.execute_code = AsyncMock(return_value=ExecuteResult(
            code="def factorial(n):\n    if n == 0:\n        return 1\n    return n * factorial(n-1)",
            execution_time=0.1,
            output="",
            success=True,
        ))
        
        plan_result = PlanResult(
            plan="def factorial(n):",
            confidence=0.8,
            reasoning="Simple recursive factorial function",
        )
        
        state = TriModelState(
            task="Generate a Python function",
            plan=plan_result,
            max_iterations=3,
        )
        
        result = await phase.execute(state, mock_executor)
        
        assert result.execution is not None
        assert result.execution.code == "def factorial(n):\n    if n == 0:\n        return 1\n    return n * factorial(n-1)"
        assert result.execution.execution_time == 0.1
        assert result.execution.success is True
        assert result.iterations == 0
        
        mock_executor.execute_code.assert_called_once_with(plan_result.plan)
    
    @pytest.mark.asyncio
    async def test_execute_phase_with_plan(self):
        """Test execute phase with plan."""
        phase = ExecutePhase()
        
        # Mock executor
        mock_executor = Mock()
        mock_executor.execute_code = AsyncMock(return_value=ExecuteResult(
            code="print('Hello, World!')",
            execution_time=0.05,
            output="Hello, World!\n",
            success=True,
        ))
        
        plan_result = PlanResult(
            plan="print('Hello, World!')",
            confidence=0.9,
            reasoning="Simple print statement",
        )
        
        state = TriModelState(
            task="Generate a Python function",
            plan=plan_result,
            max_iterations=3,
        )
        
        result = await phase.execute(state, mock_executor)
        
        assert result.execution is not None
        assert result.execution.code == "print('Hello, World!')"
        assert result.execution.output == "Hello, World!\n"
        mock_executor.execute_code.assert_called_once_with("print('Hello, World!')")
    
    @pytest.mark.asyncio
    async def test_execute_phase_error_handling(self):
        """Test execute phase error handling."""
        phase = ExecutePhase()
        
        # Mock executor to raise error
        mock_executor = Mock()
        mock_executor.execute_code = AsyncMock(side_effect=Exception("Execution failed"))
        
        plan_result = PlanResult(
            plan="invalid code",
            confidence=0.8,
            reasoning="Invalid code",
        )
        
        state = TriModelState(
            task="Generate a Python function",
            plan=plan_result,
            max_iterations=3,
        )
        
        result = await phase.execute(state, mock_executor)
        
        assert result.execution is None
        assert result.iterations == 0
        assert result.error == "Execution failed"
    
    @pytest.mark.asyncio
    async def test_execute_phase_no_plan(self):
        """Test execute phase without plan."""
        phase = ExecutePhase()
        
        # Mock executor
        mock_executor = Mock()
        
        state = TriModelState(
            task="Generate a Python function",
            plan=None,
            max_iterations=3,
        )
        
        result = await phase.execute(state, mock_executor)
        
        assert result.execution is None
        assert result.iterations == 0
        assert result.error == "No plan available"
        mock_executor.execute_code.assert_not_called()


class TestTestPhase:
    """Test TestPhase functionality."""
    
    def test_test_phase_creation(self):
        """Test test phase creation."""
        phase = TestPhase()
        
        assert phase.name == "test"
        assert phase.timeout == 120
        assert phase.min_coverage = 80
    
    @pytest.mark.asyncio
    async def test_test_phase_execution(self):
        """Test test phase execution."""
        phase = TestPhase()
        
        # Mock tester
        mock_tester = Mock()
        mock_tester.run_tests = AsyncMock(return_value=TestResult(
            passed=True,
            test_results=[
                {"name": "test_factorial_0", "passed": True},
                {"name": "test_factorial_5", "passed": True},
            ],
            coverage=90,
            execution_time=0.2,
        ))
        
        execute_result = ExecuteResult(
            code="def factorial(n):\n    if n == 0:\n        return 1\n    return n * factorial(n-1)",
            execution_time=0.1,
            output="",
            success=True,
        )
        
        state = TriModelState(
            task="Generate a Python function",
            execution=execute_result,
            max_iterations=3,
        )
        
        result = await phase.execute(state, mock_tester)
        
        assert result.test is not None
        assert result.test.passed is True
        assert result.test.coverage == 90
        assert result.test.execution_time == 0.2
        assert len(result.test.test_results) == 2
        assert result.iterations == 0
        
        mock_tester.run_tests.assert_called_once_with(execute_result.code)
    
    @pytest.mark.asyncio
    async def test_test_phase_with_min_coverage(self):
        """Test test phase with minimum coverage."""
        phase = TestPhase(min_coverage=80)
        
        # Mock tester
        mock_tester = Mock()
        mock_tester.run_tests = AsyncMock(return_value=TestResult(
            passed=False,
            test_results=[
                {"name": "test_factorial_0", "passed": True},
                {"name": "test_factorial_5", "passed": False},
            ],
            coverage=60,  # Below minimum
            execution_time=0.2,
        ))
        
        execute_result = ExecuteResult(
            code="def factorial(n):\n    if n == 0:\n        return 1\n    return n * factorial(n-1)",
            execution_time=0.1,
            output="",
            success=True,
        )
        
        state = TriModelState(
            task="Generate a Python function",
            execution=execute_result,
            max_iterations=3,
        )
        
        result = await phase.execute(state, mock_tester)
        
        assert result.test is not None
        assert result.test.passed is False
        assert result.test.coverage == 60
        mock_tester.run_tests.assert_called_once_with(execute_result.code)
    
    @pytest.mark.asyncio
    async def test_test_phase_error_handling(self):
        """Test test phase error handling."""
        phase = TestPhase()
        
        # Mock tester to raise error
        mock_tester = Mock()
        mock_tester.run_tests = AsyncMock(side_effect=Exception("Testing failed"))
        
        execute_result = ExecuteResult(
            code="def factorial(n):\n    if n == 0:\n        return 1\n    return n * factorial(n-1)",
            execution_time=0.1,
            output="",
            success=True,
        )
        
        state = TriModelState(
            task="Generate a Python function",
            execution=execute_result,
            max_iterations=3,
        )
        
        result = await phase.execute(state, mock_tester)
        
        assert result.test is None
        assert result.iterations == 0
        assert result.error == "Testing failed"
    
    @pytest.mark.asyncio
    async def test_test_phase_no_execution(self):
        """Test test phase without execution."""
        phase = TestPhase()
        
        # Mock tester
        mock_tester = Mock()
        
        state = TriModelState(
            task="Generate a Python function",
            execution=None,
            max_iterations=3,
        )
        
        result = await phase.execute(state, mock_tester)
        
        assert result.test is None
        assert result.iterations == 0
        assert result.error == "No execution available"
        mock_tester.run_tests.assert_not_called()


class TestTriModelPipeline:
    """Test TriModelPipeline functionality."""
    
    def test_pipeline_creation(self):
        """Test pipeline creation."""
        pipeline = TriModelPipeline()
        
        assert pipeline.plan_phase is not None
        assert pipeline.execute_phase is not None
        assert pipeline.test_phase is not None
        assert pipeline.max_iterations == 3
        assert pipeline.bounded_replanning is True
        assert pipeline.replan_threshold == 0.7
    
    @pytest.mark.asyncio
    async def test_pipeline_execution_success(self):
        """Test successful pipeline execution."""
        pipeline = TriModelPipeline()
        
        # Mock LLM
        mock_llm = Mock()
        mock_llm.generate_plan = AsyncMock(return_value=PlanResult(
            plan="def factorial(n):",
            confidence=0.8,
            reasoning="Simple recursive factorial function",
        ))
        
        # Mock executor
        mock_executor = Mock()
        mock_executor.execute_code = AsyncMock(return_value=ExecuteResult(
            code="def factorial(n):\n    if n == 0:\n        return 1\n    return n * factorial(n-1)",
            execution_time=0.1,
            output="",
            success=True,
        ))
        
        # Mock tester
        mock_tester = Mock()
        mock_tester.run_tests = AsyncMock(return_value=TestResult(
            passed=True,
            test_results=[
                {"name": "test_factorial_0", "passed": True},
                {"name": "test_factorial_5", "passed": True},
            ],
            coverage=90,
            execution_time=0.2,
        ))
        
        result = await pipeline.execute(
            task="Generate a Python function to calculate factorial",
            llm=mock_llm,
            executor=mock_executor,
            tester=mock_tester,
            context={"language": "python"},
        )
        
        assert result.success is True
        assert result.plan is not None
        assert result.execution is not None
        assert result.test is not None
        assert result.iterations == 1
        assert result.final_output is not None
        
        # Check that all phases were called
        mock_llm.generate_plan.assert_called_once()
        mock_executor.execute_code.assert_called_once()
        mock_tester.run_tests.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_pipeline_execution_with_replanning(self):
        """Test pipeline execution with replanning."""
        pipeline = TriModelPipeline(bounded_replanning=True)
        
        # Mock LLM
        mock_llm = Mock()
        mock_llm.generate_plan = AsyncMock(side_effect=[
            PlanResult(
                plan="def factorial(n):",
                confidence=0.5,  # Low confidence - triggers replanning
                reasoning="Initial plan",
            ),
            PlanResult(
                plan="def factorial(n):\n    if n == 0:\n        return 1\n    return n * factorial(n-1)",
                confidence=0.9,  # High confidence
                reasoning="Improved plan",
            ),
        ])
        
        # Mock executor
        mock_executor = Mock()
        mock_executor.execute_code = AsyncMock(return_value=ExecuteResult(
            code="def factorial(n):\n    if n == 0:\n        return 1\n    return n * factorial(n-1)",
            execution_time=0.1,
            output="",
            success=True,
        ))
        
        # Mock tester
        mock_tester = Mock()
        mock_tester.run_tests = AsyncMock(return_value=TestResult(
            passed=True,
            test_results=[{"name": "test_factorial", "passed": True}],
            coverage=90,
            execution_time=0.2,
        ))
        
        result = await pipeline.execute(
            task="Generate a Python function to calculate factorial",
            llm=mock_llm,
            executor=mock_executor,
            tester=mock_tester,
            context={"language": "python"},
        )
        
        assert result.success is True
        assert result.iterations == 2  # Initial + replan
        assert result.plan is not None
        assert result.execution is not None
        assert result.test is not None
        
        # Check that LLM was called twice (replanning)
        assert mock_llm.generate_plan.call_count == 2
    
    @pytest.mark.asyncio
    async def test_pipeline_execution_max_iterations(self):
        """Test pipeline execution with max iterations."""
        pipeline = TriModelPipeline(max_iterations=2)
        
        # Mock LLM
        mock_llm = Mock()
        mock_llm.generate_plan = AsyncMock(return_value=PlanResult(
            plan="def factorial(n):",
            confidence=0.5,  # Low confidence
            reasoning="Plan",
        ))
        
        # Mock executor
        mock_executor = Mock()
        mock_executor.execute_code = AsyncMock(return_value=ExecuteResult(
            code="def factorial(n):",
            execution_time=0.1,
            output="",
            success=True,
        ))
        
        # Mock tester
        mock_tester = Mock()
        mock_tester.run_tests = AsyncMock(return_value=TestResult(
            passed=False,  # Tests fail
            test_results=[{"name": "test_factorial", "passed": False}],
            coverage=60,
            execution_time=0.2,
        ))
        
        result = await pipeline.execute(
            task="Generate a Python function to calculate factorial",
            llm=mock_llm,
            executor=mock_executor,
            tester=mock_tester,
            context={"language": "python"},
        )
        
        assert result.success is False
        assert result.iterations == 2  # Reached max iterations
        assert result.error == "Max iterations reached"
        
        # Check that LLM was called twice
        assert mock_llm.generate_plan.call_count == 2
    
    @pytest.mark.asyncio
    async def test_pipeline_execution_error_handling(self):
        """Test pipeline execution error handling."""
        pipeline = TriModelPipeline()
        
        # Mock LLM to raise error
        mock_llm = Mock()
        mock_llm.generate_plan = AsyncMock(side_effect=Exception("LLM error"))
        
        # Mock executor and tester (should not be called)
        mock_executor = Mock()
        mock_tester = Mock()
        
        result = await pipeline.execute(
            task="Generate a Python function",
            llm=mock_llm,
            executor=mock_executor,
            tester=mock_tester,
        )
        
        assert result.success is False
        assert result.iterations == 0
        assert result.error == "LLM error"
        assert result.plan is None
        assert result.execution is None
        assert result.test is None
        
        # Check that executor and tester were not called
        mock_executor.execute_code.assert_not_called()
        mock_tester.run_tests.assert_not_called()
    
    @pytest.mark.asyncio
    async def test_pipeline_execution_with_config(self):
        """Test pipeline execution with configuration."""
        pipeline = TriModelPipeline(
            max_iterations=5,
            bounded_replanning=False,
            replan_threshold=0.6,
        )
        
        # Mock LLM
        mock_llm = Mock()
        mock_llm.generate_plan = AsyncMock(return_value=PlanResult(
            plan="def factorial(n):",
            confidence=0.8,
            reasoning="Simple recursive factorial function",
        ))
        
        # Mock executor
        mock_executor = Mock()
        mock_executor.execute_code = AsyncMock(return_value=ExecuteResult(
            code="def factorial(n):",
            execution_time=0.1,
            output="",
            success=True,
        ))
        
        # Mock tester
        mock_tester = Mock()
        mock_tester.run_tests = AsyncMock(return_value=TestResult(
            passed=True,
            test_results=[{"name": "test_factorial", "passed": True}],
            coverage=90,
            execution_time=0.2,
        ))
        
        result = await pipeline.execute(
            task="Generate a Python function to calculate factorial",
            llm=mock_llm,
            executor=mock_executor,
            tester=mock_tester,
            context={"language": "python"},
            config={"max_iterations": 5},
        )
        
        assert result.success is True
        assert result.iterations == 1
        assert result.plan is not None
        assert result.execution is not None
        assert result.test is not None
    
    def test_get_phase_names(self):
        """Test getting phase names."""
        pipeline = TriModelPipeline()
        
        phase_names = pipeline.get_phase_names()
        
        assert len(phase_names) == 3
        assert "plan" in phase_names
        assert "execute" in phase_names
        assert "test" in phase_names
    
    def test_get_phase_info(self):
        """Test getting phase information."""
        pipeline = TriModelPipeline()
        
        phase_info = pipeline.get_phase_info()
        
        assert len(phase_info) == 3
        assert "plan" in phase_info
        assert "execute" in phase_info
        assert "test" in phase_info
        
        # Check plan phase info
        plan_info = phase_info["plan"]
        assert plan_info["name"] == "plan"
        assert plan_info["max_iterations"] == 3
        assert plan_info["timeout"] == 30
        
        # Check execute phase info
        execute_info = phase_info["execute"]
        assert execute_info["name"] == "execute"
        assert execute_info["timeout"] == 60
        
        # Check test phase info
        test_info = phase_info["test"]
        assert test_info["name"] == "test"
        assert test_info["timeout"] == 120
    
    @pytest.mark.asyncio
    async def test_health_check(self):
        """Test pipeline health check."""
        pipeline = TriModelPipeline()
        
        health = await pipeline.health_check()
        
        assert health["status"] == "healthy"
        assert "phases" in health
        assert "configuration" in health
        assert "phases"]["plan"] == "healthy"
        assert "phases"]["execute"] == "healthy"
        assert "phases"]["test"] == "healthy"


class TestGlobalTriModelPipeline:
    """Test global tri-model pipeline functions."""
    
    def test_get_tri_model_pipeline(self):
        """Test getting tri-model pipeline instance."""
        pipeline1 = get_tri_model_pipeline()
        pipeline2 = get_tri_model_pipeline()
        
        assert pipeline1 is pipeline2
        assert isinstance(pipeline1, TriModelPipeline)
    
    def test_initialize_tri_model_pipeline(self):
        """Test initializing tri-model pipeline."""
        pipeline = initialize_tri_model_pipeline()
        
        assert isinstance(pipeline, TriModelPipeline)
        assert pipeline.plan_phase is not None
        assert pipeline.execute_phase is not None
        assert pipeline.test_phase is not None
        assert pipeline.max_iterations == 3
        assert pipeline.bounded_replanning is True
        assert pipeline.replan_threshold == 0.7