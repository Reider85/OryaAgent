# OryaAgent

Senior Python coding agent with UI and long-term memory.

Ask anything about the current project: the agent can read, write and
edit files, run shell commands and search the codebase — with a
permission gate guarding write operations.

- Streaming answers and tool step cards render live in this chat.
- Sessions persist in PostgreSQL when available (fallback: in-memory).
- Permission policy: `ORYA_PERMISSION_POLICY=strict|permissive`
  (allow/deny rules in `~/.orya/permissions.yml`).
