"""DFC integration with system prompt builder (B-24 + B-30)."""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from app.core.dfc import DFC
from app.core.capability import get_language_capability_registry
from app.core.observability.spans import emit_span

logger = logging.getLogger(__name__)


class SystemPromptBuilder:
    """System prompt builder with DFC integration (B-24 + B-30)."""

    def __init__(self, dfc: DFC):
        self.dfc = dfc
        self.language_registry = get_language_capability_registry()

    def build_system_prompt(
        self,
        base_prompt: str,
        tools: List[Any],
        plan: Dict[str, Any],
        max_tokens: int = 16000,
    ) -> str:
        """Build system prompt with DFC integration."""
        with emit_span(
            "system_prompt.build",
            {
                "base_prompt_length": len(base_prompt),
                "tools_count": len(tools),
                "max_tokens": max_tokens,
            },
        ) as span:
            # Get HOT context from DFC
            hot_context = self.dfc.assemble_hot(plan)

            # Build complete prompt
            system_prompt = self._build_complete_prompt(
                base_prompt=base_prompt, hot_context=hot_context, tools=tools, plan=plan
            )

            # Truncate if needed
            if len(system_prompt) > max_tokens:
                system_prompt = self._truncate_prompt(system_prompt, max_tokens)

            span.set_attribute("final_prompt_length", len(system_prompt))
            span.set_attribute("dfc_hot_size_tokens", self.dfc._get_hot_size())
            span.set_attribute("dfc_warm_size_tokens", self.dfc._get_warm_size())
            span.set_attribute("dfc_cold_size", len(self.dfc.cold))

            return system_prompt

    def _build_complete_prompt(
        self, base_prompt: str, hot_context: str, tools: List[Any], plan: Dict[str, Any]
    ) -> str:
        """Build complete system prompt."""

        # Start with base prompt
        prompt = base_prompt

        # Add DFC context section
        prompt += f"""

=== DYNAMIC CONTEXT ===
{hot_context}
"""

        # Add language capability section (B-30)
        language_capability = self._build_language_capability_block()
        if language_capability:
            prompt += f"""

=== LANGUAGE CAPABILITY ===
{language_capability}
"""

        # Add tools section
        prompt += "=== AVAILABLE TOOLS ===\n"
        for tool in tools:
            prompt += f"- {tool.name}: {tool.description}\n"

        # Add plan information
        if plan.get("steps"):
            prompt += "\n=== PLAN ===\n"
            for i, step in enumerate(plan["steps"], 1):
                prompt += f"{i}. {step}\n"

        # Add criteria
        if plan.get("criteria"):
            prompt += "\n=== SUCCESS CRITERIA ===\n"
            for criterion in plan["criteria"]:
                prompt += f"- {criterion}\n"

        # Add instructions
        prompt += """

=== INSTRUCTIONS ===
1. Use the available tools to accomplish the task
2. Focus on the dynamic context above for relevant information
3. Keep responses concise and focused
4. When referencing code, use exact file paths and line numbers
5. Follow the plan and success criteria provided
"""

        return prompt

    def _truncate_prompt(self, prompt: str, max_tokens: int) -> str:
        """Truncate prompt to fit within token limit."""
        # Simple truncation - in production, use proper tokenizer
        if len(prompt) <= max_tokens:
            return prompt

        # Keep the most important parts
        lines = prompt.split("\n")
        truncated_lines = []
        current_length = 0

        for line in lines:
            if current_length + len(line) + 1 <= max_tokens:
                truncated_lines.append(line)
                current_length += len(line) + 1
            else:
                break

        # Add truncation indicator
        truncated_lines.append("... [truncated for length]")

        return "\n".join(truncated_lines)

    def _build_language_capability_block(self) -> Optional[str]:
        """Build language capability block for system prompt (B-30).
        
        Returns:
            Language capability block string or None if no active language
        """
        try:
            # Check if there's language capability info in DFC
            if "language_capability" in self.dfc.hot:
                capability_info = self.dfc.hot["language_capability"]
                return capability_info
            
            # Fallback: try to detect language from current context
            # This would ideally come from the session state or context
            # For now, return None (no active language capability)
            return None
            
        except Exception as e:
            logger.warning(f"Failed to build language capability block: {e}")
            return None
