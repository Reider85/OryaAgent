# Plan: M-08 — Tool: write (atomic)

**Status:** executed
**Commit message:** `M-08: tool write (atomic tmp+replace, create_dirs, path validation, registry)`

## Deviations from spec (deliberate, documented)

| Spec says | Done | Why |
|---|---|---|
| BACKLOG4: `app/tools/file_ops.py`, `args_schema=WriteInput` | `app/tools/write.py`, Annotated args (PROMPT_MVP signature `write(path, content, create_dirs=True)`) | PROMPT_MVP is the phase document; repo convention since M-07 |
| BACKLOG4: temp `{path}.tmp.{pid}` + `os.rename` | `tempfile.mkstemp(dir=same_dir)` + `os.replace` | `os.rename` fails on Windows when target exists; `mkstemp` guarantees a unique name (same precedent as `importers.py`) |
| BACKLOG4: dev-mode `{path}.bak` when `ORYA_DEV=true` | Skipped | Not in PROMPT_MVP; no `Settings.orya_dev` field — keeps MVP lean (can return in ALPHA with cost-tracking config) |
| Atomicity unspecified vs durability | tmp is flushed + `fsync`-ed before `os.replace` | Real crash-atomicity (TRIZ #9); few lines, no API change |
| Permissions unspecified | Existing target mode preserved on overwrite (`stat.S_IMODE`); new files keep mkstemp's `0600` | mkstemp would otherwise silently tighten permissions of tracked files |

## Result

- `app/tools/write.py` — `@tool async write(path, content, create_dirs=True) -> str`: `validate_path` before any fs mutation, directory-target rejection, optional parent-dir creation, atomic `_write_atomic` (mkstemp → write → flush+fsync → mode preserve → `os.replace`; temp cleaned up on any failure), returns `"Wrote {n} bytes to {resolved}"` (utf-8 byte count). Not cached (side-effect tool); docstring notes strict-policy `interrupt_before` gating (M-13).
- `app/tools/__init__.py` / `app/core/tools.py` — `write` exported and registered: `get_tools()` → `[read, write]`.
- `tests/unit/test_tools.py` — +15 tests (37 total in file): create/overwrite/empty/utf-8-bytes, `create_dirs` (default + false), path escape/traversal, directory target, atomicity (spy on `os.replace`: single call, same-dir tmp, no leftover), temp cleanup on failure, no cache usage, write→read invalidation via mtime, graph e2e write. Registry/bind_tools assertions updated to `["read", "write"]`.
- README: M-07 (missed by previous commit) + M-08 ✅ in Phase Progress.
- Verified: 180 unit tests green (13 integration skipped — no env keys), `ruff check` + `ruff format --check` clean.
