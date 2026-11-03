"""Custom loop factory for Windows to ensure SelectorEventLoop usage.

This module provides a loop factory that always returns SelectorEventLoop
on Windows to avoid ProactorEventLoop incompatibility with psycopg async.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable


def selector_loop_factory(use_subprocess: bool = False) -> Callable[[], asyncio.AbstractEventLoop]:
    """Return a SelectorEventLoop factory.
    
    On Windows, this always returns SelectorEventLoop to avoid ProactorEventLoop
    which is incompatible with psycopg async connections used by the checkpointer.
    On other platforms, defaults to asyncio's standard behavior.
    """
    if use_subprocess:
        # When using subprocess (e.g., uvicorn --reload), use the standard behavior
        return asyncio.SelectorEventLoop
    
    # On Windows, always use SelectorEventLoop
    import sys
    if sys.platform == "win32":
        return asyncio.SelectorEventLoop
    
    # On other platforms, use the standard asyncio factory
    return asyncio.SelectorEventLoop