"""L0 memory layer (M-25): MD files behind a stable seam.

``MDStore`` is the only writer/reader of the L0 files; the system-prompt
builder (``app.core.prompt``) and the ``/learn`` endpoint (M-26) both go
through it, so PROMPT_MVP §4.5's memory contract — ``append(file, content)``,
``read(file)``, ``mtime(file)`` — has exactly one implementation.
"""

from __future__ import annotations

from app.core.memory.audit import (
    MEMORY_AUDIT_FILENAME,
    drain_memory_audits,
    record_memory_op,
)
from app.core.memory.md_store import (
    DEFAULT_MAX_BYTES,
    FILES,
    MAX_BYTES,
    MDStore,
    get_md_store,
)
from app.core.memory.models import (
    ID_PREFIXES,
    KIND_BY_FILE,
    MemoryItem,
    kind_for,
    next_id,
    parse_entries,
)

__all__ = [
    "DEFAULT_MAX_BYTES",
    "FILES",
    "ID_PREFIXES",
    "KIND_BY_FILE",
    "MAX_BYTES",
    "MEMORY_AUDIT_FILENAME",
    "MDStore",
    "MemoryItem",
    "drain_memory_audits",
    "get_md_store",
    "kind_for",
    "next_id",
    "parse_entries",
    "record_memory_op",
]
