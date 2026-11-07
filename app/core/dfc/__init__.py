"""DFC package - Dynamic Fast Context."""

from .dfc import DFC, HeatCache, CompactSummary, BackgroundCompactor, get_dfc, initialize_dfc
from .metrics import DFCMetrics, get_dfc_metrics
from .integration import DFCIntegration, get_dfc_integration, initialize_dfc_integration

__all__ = [
    "DFC",
    "HeatCache", 
    "CompactSummary",
    "BackgroundCompactor",
    "get_dfc",
    "initialize_dfc",
    "DFCMetrics",
    "get_dfc_metrics",
    "DFCIntegration",
    "get_dfc_integration",
    "initialize_dfc_integration",
]