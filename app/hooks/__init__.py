"""Hooks framework (B-04, B-05).

This package contains various hooks for the OryaAgent hooks framework.
"""

# Import to ensure hooks are registered when the module is loaded
from . import auto_format, auto_lint, cache_invalidation, examples

__all__ = [
    "auto_format",
    "auto_lint",
    "cache_invalidation",
    "examples",
]
