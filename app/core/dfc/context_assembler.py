"""ContextAssembler - integrates DFC with system prompt builder."""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from app.core.observability.spans import emit_span

logger = logging.getLogger(__name__)


class ContextAssembler:
    """Assembles context from DFC layers for system prompt."""

    def __init__(self, dfc: Any):  # DFC instance
        self.dfc = dfc

    def assemble_system_prompt(
        self,
        base_prompt: str,
        tools: list,
        plan: Dict[str, Any],
        max_tokens: int = 16000,
    ) -> str:
        """Assemble complete system prompt with DFC integration."""
        with emit_span(
            "dfc.assemble_system_prompt",
            {
                "base_prompt_length": len(base_prompt),
                "tools_count": len(tools),
                "max_tokens": max_tokens,
            },
        ) as span:
            # Get HOT context from DFC
            hot_context = self.dfc.assemble_hot(plan)

            # Combine base prompt with HOT context
            system_prompt = f"""{base_prompt}

=== DYNAMIC CONTEXT ===
{hot_context}

=== AVAILABLE TOOLS ===
"""

            # Add tools
            for tool in tools:
                system_prompt += f"- {tool.name}: {tool.description}\n"

            # Add system instructions
            system_prompt += """
=== INSTRUCTIONS ===
1. Use the available tools to accomplish the task
2. Focus on the dynamic context above for relevant information
3. Keep responses concise and focused
4. When referencing code, use exact file paths and line numbers
"""

            # Truncate if needed
            if len(system_prompt) > max_tokens:
                system_prompt = self._truncate_prompt(system_prompt, max_tokens)

            span.set_attribute("final_prompt_length", len(system_prompt))
            span.set_attribute("dfc_hot_size_tokens", self.dfc._get_hot_size())
            span.set_attribute("dfc_warm_size_tokens", self.dfc._get_warm_size())
            span.set_attribute("dfc_cold_size", len(self.dfc.cold))

            return system_prompt

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

    def add_dynamic_suffix(self, prompt: str, context: Dict[str, Any]) -> str:
        """Add dynamic suffix to prompt based on context."""
        dynamic_parts = []

        # Add recent activity from HOT layer
        if self.dfc.hot:
            dynamic_parts.append("Recent activity:")
            for key, value in list(self.dfc.hot.items())[-5:]:  # Last 5 items
                dynamic_parts.append(f"- {key}: {value[:50]}...")

        # Add prefetch hints
        if context.get("prefetch_hints"):
            dynamic_parts.append("Prefetch hints:")
            for hint in context["prefetch_hints"][:3]:  # Top 3 hints
                dynamic_parts.append(f"- {hint}")

        # Add cold layer summaries if relevant
        if context.get("include_cold_summaries") and self.dfc.cold:
            dynamic_parts.append("Relevant summaries:")
            for summary in self.dfc.cold[-3:]:  # Last 3 summaries
                dynamic_parts.append(f"- {summary.summary}")

        if dynamic_parts:
            return f"{prompt}\n\n{' '.join(dynamic_parts)}"

        return prompt
