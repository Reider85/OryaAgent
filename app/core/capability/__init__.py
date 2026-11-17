"""Multi-language programming capabilities for OryaAgent BETA (B-30).

This module provides comprehensive language-specific programming capabilities
including LSP integration, skill-bundles, hook-sets, and automated tooling
for Java, Rust, Go, JavaScript, and Frontend development.
"""

from .language_registry import (
    LanguageCapability,
    LanguageCapabilityRegistry,
    get_language_capability_registry,
    reset_language_capability_registry,
)
from .program import agent_program

__all__ = [
    "LanguageCapability",
    "LanguageCapabilityRegistry", 
    "get_language_capability_registry",
    "reset_language_capability_registry",
    "agent_program",
]