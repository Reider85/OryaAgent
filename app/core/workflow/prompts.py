"""Prompts for Tri-Model Pipeline."""

from __future__ import annotations

import logging
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


class PlannerPrompt:
    """Prompt template for planner model."""
    
    @staticmethod
    def build_prompt(
        task: str,
        context: str = "",
        available_tools: List[str] = None,
        session_history: List[str] = None,
        max_steps: int = 5,
    ) -> str:
        """Build planning prompt."""
        tools_text = ""
        if available_tools:
            tools_text = "Available Tools:\n" + "\n".join([f"- {tool}" for tool in available_tools])
        
        history_text = ""
        if session_history:
            history_text = "Recent Activity:\n" + "\n".join([f"- {item}" for item in session_history[-3:]])
        
        return f"""You are an expert planning assistant. Your task is to break down the following task into clear, executable steps.

Task: {task}

{context}

{history_text}

{tools_text}

Planning Guidelines:
1. Break the task into {max_steps} or fewer logical steps
2. Each step should be specific and actionable
3. Include success criteria for each step
4. Consider the available tools for each step
5. Provide prefetch hints for optimization
6. Select the appropriate model tier (small/large/tournament)

Return your plan in the following JSON format:
{{
  "steps": [
    "Step 1 description",
    "Step 2 description",
    "Step 3 description"
  ],
  "criteria": [
    "Criterion 1 description",
    "Criterion 2 description"
  ],
  "prefetch_hints": [
    "Hint 1 for optimization",
    "Hint 2 for optimization"
  ],
  "tier": "small"  // small, large, or tournament
}}

Important: Only return the JSON object, no additional text."""


class TesterPrompt:
    """Prompt template for tester model."""
    
    @staticmethod
    def build_prompt(
        plan: Dict,
        execution_result: Dict,
        session_context: str = "",
        run_tests: bool = False,  # False in BETA, True in PROD
    ) -> str:
        """Build testing prompt."""
        plan_text = f"""Plan:
Steps:
{chr(10).join([f"{i+1}. {step}" for i, step in enumerate(plan.get('steps', []))])}

Success Criteria:
{chr(10).join([f"- {criterion}" for criterion in plan.get('criteria', [])])}

Prefetch Hints:
{chr(10).join([f"- {hint}" for hint in plan.get('prefetch_hints', [])])}"""

        execution_text = f"""Execution Results:
Status: {execution_result.get('status', 'unknown')}
Message: {execution_result.get('message', '')}
Tools Used: {', '.join(execution_result.get('tools_used', []))}
Output: {execution_result.get('output', '')}"""

        session_text = f"""Session Context:
{session_context}""" if session_text else ""

        test_instruction = ""
        if run_tests:
            test_instruction = """
Additional Testing Instructions:
1. Verify each step was completed successfully
2. Check if all success criteria were met
3. Identify any discrepancies between plan and execution
4. Provide specific feedback on failures
5. Suggest improvements if needed"""

        return f"""You are an expert testing assistant. Your task is to evaluate the execution results against the original plan criteria.

{plan_text}

{execution_text}

{session_text}

{test_instruction}

Evaluation Guidelines:
1. Carefully compare the execution results with the plan steps
2. Check if all success criteria were met
3. Look for any discrepancies or issues
4. Provide clear feedback on the execution quality
5. Include confidence level in your assessment

Return your verdict in the following JSON format:
{{
  "verdict": "pass|fail",
  "message": "Detailed explanation of your verdict",
  "confidence": 0.95,
  "failed_criteria": ["Criterion 1 that failed", "Criterion 2 that failed"],
  "execution_diff": "Brief description of key differences between plan and execution"
}}

Important: Only return the JSON object, no additional text."""


class ReplannerPrompt:
    """Prompt template for replanning."""
    
    @staticmethod
    def build_prompt(
        original_plan: Dict,
        verdict: Dict,
        execution_result: Dict,
        session_context: str = "",
    ) -> str:
        """Build replanning prompt."""
        original_plan_text = f"""Original Plan:
Steps:
{chr(10).join([f"{i+1}. {step}" for i, step in enumerate(original_plan.get('steps', []))])}

Criteria:
{chr(10).join([f"- {criterion}" for criterion in original_plan.get('criteria', [])])}"""

        verdict_text = f"""Verdict:
Status: {verdict.get('verdict', 'unknown')}
Message: {verdict.get('message', '')}
Failed Criteria: {', '.join(verdict.get('failed_criteria', []))}
Confidence: {verdict.get('confidence', 0)}"""

        execution_text = f"""Execution Results:
{execution_result.get('output', '')}"""

        session_text = f"""Session Context:
{session_context}""" if session_text else ""

        return f"""You are an expert planning assistant. The original plan execution failed, and you need to create an improved plan.

{original_plan_text}

{verdict_text}

{execution_text}

{session_text}

Replanning Guidelines:
1. Analyze why the original plan failed
2. Address all failed criteria
3. Improve the plan steps based on execution feedback
4. Keep successful elements of the original plan
5. Provide better prefetch hints if needed
6. Adjust model tier if necessary

Return your improved plan in the following JSON format:
{{
  "steps": [
    "Improved Step 1",
    "Improved Step 2",
    "Improved Step 3"
  ],
  "criteria": [
    "Updated Criterion 1",
    "Updated Criterion 2"
  ],
  "prefetch_hints": [
    "Improved Hint 1",
    "Improved Hint 2"
  ],
  "tier": "small"
}}

Important: Only return the JSON object, no additional text."""


class SystemPromptBuilder:
    """Build system prompts for Tri-Model Pipeline."""
    
    def __init__(self):
        self.planner_prompt = PlannerPrompt()
        self.tester_prompt = TesterPrompt()
        self.replanner_prompt = ReplannerPrompt()
    
    def build_planner_system_prompt(self) -> str:
        """Build system prompt for planner model."""
        return """You are an expert planning assistant for software development tasks. You excel at breaking down complex tasks into manageable steps and providing clear success criteria.

Your role is to:
1. Analyze the task and understand requirements
2. Break down into logical, sequential steps
3. Define specific success criteria for each step
4. Consider available tools and optimize with prefetch hints
5. Select appropriate model tier for the task

You are precise, methodical, and focused on creating executable plans."""

    def build_executor_system_prompt(self) -> str:
        """Build system prompt for executor model."""
        return """You are an expert execution assistant for software development tasks. You excel at carrying out plans precisely and efficiently.

Your role is to:
1. Follow the provided plan step by step
2. Use available tools appropriately
3. Execute each step completely and accurately
4. Provide clear output for each step
5. Handle errors gracefully and report issues

You are thorough, precise, and focused on successful execution."""

    def build_tester_system_prompt(self) -> str:
        """Build system prompt for tester model."""
        return """You are an expert testing assistant for software development tasks. You excel at evaluating execution results against plans and providing accurate feedback.

Your role is to:
1. Compare execution results against the original plan
2. Check if all success criteria were met
3. Identify discrepancies and issues
4. Provide clear verdicts with confidence levels
5. Suggest specific improvements when needed

You are analytical, detail-oriented, and focused on quality assurance."""

    def build_replanner_system_prompt(self) -> str:
        """Build system prompt for replanner model."""
        return """You are an expert replanning assistant for software development tasks. You excel at improving plans based on execution feedback.

Your role is to:
1. Analyze why the original plan failed
2. Address all failed criteria specifically
3. Create improved plans based on execution results
4. Keep successful elements of the original plan
5. Optimize for better execution in the next attempt

You are analytical, adaptive, and focused on continuous improvement."""