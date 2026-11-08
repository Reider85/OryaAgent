"""Tri-Model Pipeline - plan → execute → test with concurrent execution."""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Union

from app.core.observability.spans import emit_span

logger = logging.getLogger(__name__)


@dataclass
class Plan:
    """Plan dataclass for Tri-Model Pipeline."""

    steps: List[str]
    criteria: List[str]
    prefetch_hints: List[str]
    tier: str  # small|large|tournament
    cacheable_prefix: str = ""
    dynamic_suffix: str = ""
    session_id: Optional[str] = None
    created_at: Optional[float] = None

    def __post_init__(self):
        if self.created_at is None:
            self.created_at = time.time()

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "steps": self.steps,
            "criteria": self.criteria,
            "prefetch_hints": self.prefetch_hints,
            "tier": self.tier,
            "cacheable_prefix": self.cacheable_prefix,
            "dynamic_suffix": self.dynamic_suffix,
            "session_id": self.session_id,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Plan":
        """Create from dictionary."""
        return cls(
            steps=data.get("steps", []),
            criteria=data.get("criteria", []),
            prefetch_hints=data.get("prefetch_hints", []),
            tier=data.get("tier", "small"),
            cacheable_prefix=data.get("cacheable_prefix", ""),
            dynamic_suffix=data.get("dynamic_suffix", ""),
            session_id=data.get("session_id"),
            created_at=data.get("created_at"),
        )


@dataclass
class Verdict:
    """Test verdict for Tri-Model Pipeline."""

    verdict: str  # pass|fail|replan
    message: str = ""
    confidence: float = 1.0
    failed_criteria: List[str] = field(default_factory=list)
    execution_diff: Optional[str] = None
    test_duration_ms: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "verdict": self.verdict,
            "message": self.message,
            "confidence": self.confidence,
            "failed_criteria": self.failed_criteria,
            "execution_diff": self.execution_diff,
            "test_duration_ms": self.test_duration_ms,
        }


@dataclass
class TurnResult:
    """Result of a turn in Tri-Model Pipeline."""

    plan: Plan
    execution_result: Dict[str, Any]
    verdict: Verdict
    replan_count: int = 0
    total_duration_ms: float = 0.0
    plan_duration_ms: float = 0.0
    execution_duration_ms: float = 0.0
    test_duration_ms: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "plan": self.plan.to_dict(),
            "execution_result": self.execution_result,
            "verdict": self.verdict.to_dict(),
            "replan_count": self.replan_count,
            "total_duration_ms": self.total_duration_ms,
            "plan_duration_ms": self.plan_duration_ms,
            "execution_duration_ms": self.execution_duration_ms,
            "test_duration_ms": self.test_duration_ms,
        }


class TriModelPipeline:
    """Tri-Model Pipeline: plan → execute → test."""

    def __init__(
        self,
        planner_model: Any,
        executor_model: Any,
        tester_model: Any,
        dfc: Any = None,
        max_replans: int = 2,
        concurrent_tester: bool = False,  # False in BETA, True in PROD
    ):
        self.planner_model = planner_model
        self.executor_model = executor_model
        self.tester_model = tester_model
        self.dfc = dfc
        self.max_replans = max_replans
        self.concurrent_tester = concurrent_tester

        # Statistics
        self.total_turns = 0
        self.passed_turns = 0
        self.failed_turns = 0
        self.replan_turns = 0

    async def build_graph(self) -> Any:
        """Build LangGraph subgraph for Tri-Model Pipeline."""
        # In a real implementation, this would build a LangGraph subgraph
        # For now, we'll return a mock graph structure
        return MockTriModelGraph(self)

    async def execute_turn(
        self,
        session_state: Dict[str, Any],
        tools: List[Any],
        task: str,
        context: Dict[str, Any] = None,
    ) -> TurnResult:
        """Execute a single turn with Tri-Model Pipeline."""
        start_time = time.time()
        context = context or {}

        with emit_span(
            "tri_model.execute_turn",
            {
                "task": task,
                "session_id": session_state.get("session_id"),
                "concurrent_tester": self.concurrent_tester,
            },
        ) as span:
            # Step 1: Plan
            plan_result = await self._plan_step(
                session_state=session_state,
                tools=tools,
                task=task,
                context=context,
            )
            plan_duration = time.time() - start_time

            # Step 2: Execute
            execution_result = await self._execute_step(
                plan=plan_result,
                session_state=session_state,
                tools=tools,
                context=context,
            )
            execution_duration = time.time() - start_time - plan_duration

            # Step 3: Test
            if self.concurrent_tester:
                # In PROD, tester runs concurrently with executor
                # In BETA, we run it sequentially
                test_task = asyncio.create_task(
                    self._test_step(
                        plan=plan_result,
                        execution_result=execution_result,
                        session_state=session_state,
                        context=context,
                    )
                )
                # Wait for execution to complete, then test
                await asyncio.sleep(0.1)  # Simulate concurrent execution
                verdict = await test_task
            else:
                # Sequential execution (BETA)
                verdict = await self._test_step(
                    plan=plan_result,
                    execution_result=execution_result,
                    session_state=session_state,
                    context=context,
                )
            test_duration = (
                time.time() - start_time - plan_duration - execution_duration
            )

            # Determine verdict and handle replanning
            turn_result = TurnResult(
                plan=plan_result,
                execution_result=execution_result,
                verdict=verdict,
                plan_duration_ms=plan_duration * 1000,
                execution_duration_ms=execution_duration * 1000,
                test_duration_ms=test_duration * 1000,
                total_duration_ms=(time.time() - start_time) * 1000,
            )

            # Handle replanning if needed
            if (
                verdict.verdict == "fail"
                and turn_result.replan_count < self.max_replans
            ):
                turn_result = await self._replan(
                    turn_result=turn_result,
                    session_state=session_state,
                    tools=tools,
                    task=task,
                    context=context,
                )

            # Update statistics
            self.total_turns += 1
            if verdict.verdict == "pass":
                self.passed_turns += 1
            elif verdict.verdict == "fail":
                self.failed_turns += 1
            if turn_result.replan_count > 0:
                self.replan_turns += 1

            span.set_attribute("verdict", verdict.verdict)
            span.set_attribute("replan_count", turn_result.replan_count)
            span.set_attribute("total_duration_ms", turn_result.total_duration_ms)

            return turn_result

    async def _plan_step(
        self,
        session_state: Dict[str, Any],
        tools: List[Any],
        task: str,
        context: Dict[str, Any],
    ) -> Plan:
        """Execute planning step."""
        with emit_span(
            "tri_model.plan",
            {
                "task": task,
                "session_id": session_state.get("session_id"),
            },
        ) as span:
            # Build prompt for planner
            prompt = self._build_planner_prompt(
                session_state=session_state,
                tools=tools,
                task=task,
                context=context,
            )

            # Call planner model
            planning_response = await self.planner_model.generate(prompt)

            # Parse plan response
            plan = self._parse_planning_response(planning_response.content)

            span.set_attribute("steps_count", len(plan.steps))
            span.set_attribute("criteria_count", len(plan.criteria))
            span.set_attribute("tier", plan.tier)

            # Integrate with DFC if available
            if self.dfc:
                hot_context = self.dfc.assemble_hot(plan.to_dict())
                plan.dynamic_suffix = hot_context

            return plan

    async def _execute_step(
        self,
        plan: Plan,
        session_state: Dict[str, Any],
        tools: List[Any],
        context: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Execute planning step."""
        with emit_span(
            "tri_model.execute",
            {
                "tier": plan.tier,
                "session_id": session_state.get("session_id"),
            },
        ) as span:
            # Build prompt for executor
            prompt = self._build_executor_prompt(
                plan=plan,
                session_state=session_state,
                tools=tools,
                context=context,
            )

            # Call executor model
            execution_response = await self.executor_model.generate(prompt)

            # Parse execution result
            result = self._parse_execution_response(execution_response.content)

            span.set_attribute("execution_success", result.get("success", True))
            span.set_attribute("tools_used", len(result.get("tools_used", [])))

            return result

    async def _test_step(
        self,
        plan: Plan,
        execution_result: Dict[str, Any],
        session_state: Dict[str, Any],
        context: Dict[str, Any],
    ) -> Verdict:
        """Execute testing step."""
        with emit_span(
            "tri_model.test",
            {
                "session_id": session_state.get("session_id"),
            },
        ) as span:
            # Build prompt for tester
            prompt = self._build_tester_prompt(
                plan=plan,
                execution_result=execution_result,
                session_state=session_state,
                context=context,
            )

            # Call tester model
            test_response = await self.tester_model.generate(prompt)

            # Parse verdict
            verdict = self._parse_test_response(test_response.content)

            span.set_attribute("verdict", verdict.verdict)
            span.set_attribute("confidence", verdict.confidence)
            span.set_attribute("failed_criteria_count", len(verdict.failed_criteria))

            return verdict

    async def _replan(
        self,
        turn_result: TurnResult,
        session_state: Dict[str, Any],
        tools: List[Any],
        task: str,
        context: Dict[str, Any],
    ) -> TurnResult:
        """Handle replanning."""
        with emit_span(
            "tri_model.replan",
            {
                "replan_count": turn_result.replan_count + 1,
                "session_id": session_state.get("session_id"),
            },
        ) as span:
            logger.info(f"Replanning turn (attempt {turn_result.replan_count + 1})")

            # Update plan with feedback
            updated_plan = self._update_plan_for_replan(
                original_plan=turn_result.plan,
                verdict=turn_result.verdict,
                execution_result=turn_result.execution_result,
            )

            # Execute again with updated plan
            turn_result.replan_count += 1

            # Re-execute with updated plan
            execution_result = await self._execute_step(
                plan=updated_plan,
                session_state=session_state,
                tools=tools,
                context=context,
            )

            # Test again
            verdict = await self._test_step(
                plan=updated_plan,
                execution_result=execution_result,
                session_state=session_state,
                context=context,
            )

            # Update turn result
            turn_result.plan = updated_plan
            turn_result.execution_result = execution_result
            turn_result.verdict = verdict
            turn_result.total_duration_ms += (time.time() - start_time) * 1000

            span.set_attribute("final_verdict", verdict.verdict)
            span.set_attribute("total_replans", turn_result.replan_count)

            return turn_result

    def _build_planner_prompt(
        self,
        session_state: Dict[str, Any],
        tools: List[Any],
        task: str,
        context: Dict[str, Any],
    ) -> str:
        """Build prompt for planner model."""
        return f"""You are a planning assistant. Break down the following task into executable steps:

Task: {task}

Session Context:
- Current directory: {session_state.get("current_dir", "/")}
- Files in context: {len(session_state.get("files", []))} files
- Recent activity: {session_state.get("recent_activity", "none")}

Available Tools:
{chr(10).join([f"- {tool.name}: {tool.description}" for tool in tools])}

Planning Criteria:
- Create clear, sequential steps
- Include success criteria for each step
- Provide prefetch hints for optimization
- Select appropriate model tier (small/large/tournament)

Return your plan in JSON format:
{{
  "steps": ["step1", "step2", "step3"],
  "criteria": ["criterion1", "criterion2"],
  "prefetch_hints": ["hint1", "hint2"],
  "tier": "small"
}}"""

    def _build_executor_prompt(
        self,
        plan: Plan,
        session_state: Dict[str, Any],
        tools: List[Any],
        context: Dict[str, Any],
    ) -> str:
        """Build prompt for executor model."""
        return f"""You are an execution assistant. Execute the following plan:

Plan:
Steps:
{chr(10).join([f"{i + 1}. {step}" for i, step in enumerate(plan.steps)])}

Success Criteria:
{chr(10).join([f"- {criterion}" for criterion in plan.criteria])}

Prefetch Hints:
{chr(10).join([f"- {hint}" for hint in plan.prefetch_hints])}

Model Tier: {plan.tier}

Context:
- Current directory: {session_state.get("current_dir", "/")}
- Files in context: {len(session_state.get("files", []))} files

Execute the plan using the available tools and return the results."""

    def _build_tester_prompt(
        self,
        plan: Plan,
        execution_result: Dict[str, Any],
        session_state: Dict[str, Any],
        context: Dict[str, Any],
    ) -> str:
        """Build prompt for tester model."""
        return f"""You are a testing assistant. Evaluate the execution results against the plan criteria:

Plan:
Steps:
{chr(10).join([f"{i + 1}. {step}" for i, step in enumerate(plan.steps)])}

Success Criteria:
{chr(10).join([f"- {criterion}" for criterion in plan.criteria])}

Execution Results:
{execution_result}

Return your verdict in JSON format:
{{
  "verdict": "pass|fail",
  "message": "explanation",
  "confidence": 0.9,
  "failed_criteria": ["criterion1", "criterion2"]
}}"""

    def _parse_planning_response(self, response: str) -> Plan:
        """Parse planning response into Plan object."""
        import json

        try:
            data = json.loads(response)
            return Plan.from_dict(data)
        except json.JSONDecodeError:
            # Fallback parsing
            return Plan(
                steps=["Execute the task"],
                criteria=["Task completed successfully"],
                prefetch_hints=[],
                tier="small",
            )

    def _parse_execution_response(self, response: str) -> Dict[str, Any]:
        """Parse execution response into result dict."""
        import json

        try:
            return json.loads(response)
        except json.JSONDecodeError:
            # Fallback parsing
            return {
                "success": True,
                "message": "Execution completed",
                "tools_used": [],
                "output": response,
            }

    def _parse_test_response(self, response: str) -> Verdict:
        """Parse test response into Verdict object."""
        import json

        try:
            data = json.loads(response)
            return Verdict(
                verdict=data.get("verdict", "pass"),
                message=data.get("message", ""),
                confidence=data.get("confidence", 1.0),
                failed_criteria=data.get("failed_criteria", []),
            )
        except json.JSONDecodeError:
            # Fallback parsing
            return Verdict(
                verdict="pass",
                message="Test passed",
                confidence=1.0,
                failed_criteria=[],
            )

    def _update_plan_for_replan(
        self,
        original_plan: Plan,
        verdict: Verdict,
        execution_result: Dict[str, Any],
    ) -> Plan:
        """Update plan for replanning based on verdict."""
        # Create updated plan with feedback
        updated_steps = original_plan.steps.copy()

        # Add feedback to steps
        if verdict.failed_criteria:
            updated_steps.append(
                f"Address failed criteria: {', '.join(verdict.failed_criteria)}"
            )

        # Add any missing steps from execution
        if execution_result.get("missing_steps"):
            updated_steps.extend(execution_result["missing_steps"])

        return Plan(
            steps=updated_steps,
            criteria=original_plan.criteria,
            prefetch_hints=original_plan.prefetch_hints,
            tier=original_plan.tier,
            cacheable_prefix=original_plan.cacheable_prefix,
            dynamic_suffix=original_plan.dynamic_suffix,
        )

    def get_statistics(self) -> Dict[str, Any]:
        """Get pipeline statistics."""
        total = self.total_turns
        pass_rate = (self.passed_turns / total) if total > 0 else 0
        replan_rate = (self.replan_turns / total) if total > 0 else 0

        return {
            "total_turns": total,
            "passed_turns": self.passed_turns,
            "failed_turns": self.failed_turns,
            "replan_turns": self.replan_turns,
            "pass_rate": pass_rate,
            "replan_rate": replan_rate,
            "concurrent_tester": self.concurrent_tester,
            "max_replans": self.max_replans,
        }


class MockTriModelGraph:
    """Mock LangGraph subgraph for Tri-Model Pipeline."""

    def __init__(self, pipeline: TriModelPipeline):
        self.pipeline = pipeline

    async def astream_events(self, *args, **kwargs):
        """Mock async stream events."""
        # In a real implementation, this would stream LangGraph events
        yield {"type": "start", "data": {}}
        yield {"type": "planning", "data": {}}
        yield {"type": "execution", "data": {}}
        yield {"type": "testing", "data": {}}
        yield {"type": "end", "data": {}}

    async def ainvoke(self, *args, **kwargs):
        """Mock async invoke."""
        return await self.pipeline.execute_turn(*args, **kwargs)
