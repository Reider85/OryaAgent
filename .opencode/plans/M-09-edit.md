# Plan: M-09 — Tool: edit (unique string-replace)

**Status:** executed
**Commit message:** `M-09: tool edit (unique string-replace, replace_all, atomic rewrite, registry)`

## Deviations from spec (deliberate, documented)

| Spec says | Done | Why |
|---|---|---|
| BACKLOG4: `app/tools/file_ops.py`, `args_schema=EditInput` | `app/tools/edit.py`, Annotated args (PROMPT_MVP signature `edit(path, old_string, new_string)`) | PROMPT_MVP is the phase document; repo convention since M-07 (same as M-08 vs `write`) |
| PROMPT_MVP: 3 args; BACKLOG4: + `replace_all: bool = False` | Optional 4th parameter, default `False` | Precedent M-08 kept BACKLOG4's `create_dirs` on the PROMPT_MVP signature; without `replace_all` a non-unique `old_string` is unresolvable |
| Atomicity: "read → modify in memory → write через temp-file + rename" | read→replace→`_write_atomic` (imported from `write.py`: mkstemp → flush+fsync → mode preserve → `os.replace`) in one `asyncio.to_thread` | Reuse over duplication; whole sequence in one worker thread, final write crash-atomic |
| Empty `old_string` unspecified | `ToolException("old_string must not be empty")` | `str.replace("")` inserts between every character - foot-gun |
| Encoding unspecified | bytes-read + UTF-8 decode **strict** (else `ToolException("Not a UTF-8 text file")`) | `Path.read_text` normalizes CRLF→LF silently; strict decode refuses to corrupt non-UTF-8 binaries |
| Size cap unspecified | Reuses `read.py::MAX_FILE_SIZE_BYTES` (10 MB) | Same M-23 token/memory-blowup limit, single source |
| BACKLOG5: "+ cache-invalidation hook из M-21" | No explicit hook: edit is never cached; `read` cache key includes mtime, so the next read misses automatically | Precedent M-08; tested via read→edit→read with misses==2 |
| Return message `{path}` | Resolved path (`Edited {resolved}: replaced {n} occurrence(s)`) | Consistent with M-08's `Wrote {n} bytes to {resolved}` |

## Result

- `app/tools/edit.py` — `@tool async edit(path, old_string, new_string, replace_all=False) -> str`: `validate_path` before any I/O, directory-target rejection, missing-file/size-cap/UTF-8 guards, occurrence counting (`count == 0` → `old_string not found in {path}`; `count > 1 && !replace_all` → `old_string is not unique (N occurrences)... provide more surrounding context or set replace_all=true`), exact-match replace (no regex), atomic rewrite via `_write_atomic`, OSError → `ToolException("Cannot write ...")` with temp cleanup. Not cached (side-effect tool); docstring notes strict-policy `interrupt_before` gating (M-13).
- `app/tools/__init__.py` / `app/core/tools.py` — `edit` exported and registered: `get_tools()` → `[read, write, edit]`.
- `tests/unit/test_tools.py` — +16 tests (47 total in file): unique replace, missing file, old_string not found (file unchanged), non-unique guard (file unchanged), replace_all (all occurrences + count in message), empty old_string, path escape/traversal, directory target, atomicity (spy on `os.replace`: single call, same-dir tmp, no leftover), temp cleanup on failure (original intact), CRLF preserved, non-UTF-8 rejected, no cache usage, read→edit→read invalidation via mtime, graph e2e edit. Registry/bind_tools assertions updated to `["read", "write", "edit"]`.
- README: M-09 ✅ in Phase Progress + intro ticket list extended to M-09 (was stale at M-06).
- Verified: 196 unit tests green (13 integration skipped — no env keys), `ruff check` + `ruff format --check` clean.
