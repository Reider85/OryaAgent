"""Custom loop factory for Windows to ensure SelectorEventLoop usage.

uvicorn (>=0.36, locked at 0.54) treats a custom ``--loop module:attr`` as
``Callable[[], AbstractEventLoop]``: ``Config.get_loop_factory()`` returns the
imported callable untouched and ``asyncio.Runner`` does ``loop = factory()``.
The callable must therefore return a loop **instance**, not a class — returning
``asyncio.SelectorEventLoop`` itself makes Runner bind the class and every
``loop.create_task(...)`` call fails with ``missing 1 required positional
argument: 'coro'`` (i.e. ``make dev`` crashed on startup).

SelectorEventLoop avoids the Windows ProactorEventLoop, which is incompatible
with the psycopg async connections used by the LangGraph checkpointer.
"""

from __future__ import annotations

import asyncio


def selector_loop_factory(use_subprocess: bool = False) -> asyncio.AbstractEventLoop:
    """Return a SelectorEventLoop instance.

    On Windows this avoids ProactorEventLoop, which psycopg (LangGraph
    PostgresSaver) cannot run on. On other platforms SelectorEventLoop is the
    asyncio default anyway, so the factory is safe to pass unconditionally.

    ``use_subprocess`` is accepted for signature compatibility with uvicorn's
    built-in loop factories but is unused: uvicorn invokes a custom ``--loop``
    import with no arguments.
    """
    return asyncio.SelectorEventLoop()
