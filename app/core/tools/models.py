"""Models and types for CapabilityRegistry (B-29)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class ToolFilterResult:
    """Result of a tool filtering operation."""
    
    original_count: int
    filtered_count: int
    filtered_out_count: int
    active_tools: list[str]
    filtered_out_tools: list[str]
    context_summary: dict[str, Any]
    
    @property
    def filter_ratio(self) -> float:
        """Ratio of tools filtered out."""
        return self.filtered_out_count / max(1, self.original_count)


@dataclass
class CapabilityMetrics:
    """Metrics for capability-based filtering."""
    
    total_filters: int = 0
    total_tools_processed: int = 0
    total_tools_filtered_out: int = 0
    average_active_tools: float = 0.0
    average_filter_ratio: float = 0.0
    
    def update(self, filter_result: ToolFilterResult) -> None:
        """Update metrics with a new filter result."""
        self.total_filters += 1
        self.total_tools_processed += filter_result.original_count
        self.total_tools_filtered_out += filter_result.filtered_out_count
        
        # Update averages
        if self.total_filters > 0:
            self.average_active_tools = (
                (self.average_active_tools * (self.total_filters - 1) + filter_result.filtered_count) 
                / self.total_filters
            )
            self.average_filter_ratio = (
                (self.average_filter_ratio * (self.total_filters - 1) + filter_result.filter_ratio) 
                / self.total_filters
            )