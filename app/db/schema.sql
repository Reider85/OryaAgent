-- OryaAgent PostgreSQL schema (M-03) — canonical, full state for fresh installs.
-- Incremental changes live in app/db/migrations/*.sql (applied by app.db.migrate).
-- LangGraph checkpoint tables (checkpoints, checkpoint_blobs, ...) are created
-- and migrated separately by AsyncPostgresSaver.setup() — see app/db/checkpoints.py.

-- pgcrypto: pgp_sym_encrypt/pgp_sym_decrypt for session-log encryption at
-- rest (A-05). Created unconditionally; used only when
-- ORYA_SESSION_LOG_ENCRYPTION_ENABLED=true (see app/db/session_log.py).
CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- Sessions: one row per chat session (metadata for list views; events in messages).
CREATE TABLE IF NOT EXISTS sessions (
    session_id       TEXT PRIMARY KEY,
    title            TEXT,
    provider         TEXT,
    model            TEXT,
    status           TEXT NOT NULL DEFAULT 'active'
                     CHECK (status IN ('active', 'closed', 'aborted')),
    working_dir      TEXT,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_activity_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    metadata         JSONB NOT NULL DEFAULT '{}'::jsonb
);

-- Messages: typed, query-friendly log of every model-visible message (M-14).
-- seq is the monotonically increasing position within the session.
CREATE TABLE IF NOT EXISTS messages (
    id           BIGSERIAL PRIMARY KEY,
    session_id   TEXT NOT NULL REFERENCES sessions (session_id) ON DELETE CASCADE,
    seq          INTEGER NOT NULL,
    role         TEXT NOT NULL CHECK (role IN ('system', 'user', 'assistant', 'tool')),
    content      TEXT NOT NULL DEFAULT '',
    tool_calls   JSONB,
    tool_call_id TEXT,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (session_id, seq)
);

-- Tool calls: audit of every tool invocation (args, result, approval, timing).
CREATE TABLE IF NOT EXISTS tool_calls (
    id          BIGSERIAL PRIMARY KEY,
    session_id  TEXT NOT NULL REFERENCES sessions (session_id) ON DELETE CASCADE,
    message_id  BIGINT REFERENCES messages (id) ON DELETE SET NULL,
    call_id     TEXT NOT NULL,
    tool_name   TEXT NOT NULL,
    args        JSONB NOT NULL DEFAULT '{}'::jsonb,
    result      TEXT,
    outcome     TEXT NOT NULL DEFAULT 'success'
                CHECK (outcome IN ('success', 'error', 'denied', 'aborted', 'timeout')),
    approved_by TEXT,
    duration_ms INTEGER,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Memory audit log: every L0 memory operation (append/read/compact), M-22/M-25/M-27.
CREATE TABLE IF NOT EXISTS memory_audit_log (
    id              BIGSERIAL PRIMARY KEY,
    ts              TIMESTAMPTZ NOT NULL DEFAULT now(),
    actor           TEXT NOT NULL DEFAULT 'user',
    action          TEXT NOT NULL,
    file            TEXT NOT NULL,
    content_preview TEXT,
    reason          TEXT,
    session_id      TEXT
);

CREATE INDEX IF NOT EXISTS idx_messages_session_id ON messages (session_id);
CREATE INDEX IF NOT EXISTS idx_tool_calls_session_id ON tool_calls (session_id);
CREATE INDEX IF NOT EXISTS idx_memory_audit_log_ts ON memory_audit_log (ts);

-- Branch-specific tables (B-09): optimized for branch operations and relationships
-- Sessions branches: tracks parent-child relationships and branch metadata
CREATE TABLE IF NOT EXISTS session_branches (
    branch_id          TEXT PRIMARY KEY,
    parent_session_id  TEXT NOT NULL REFERENCES sessions (session_id) ON DELETE CASCADE,
    parent_turn_id     TEXT,
    branch_name        TEXT NOT NULL,
    created_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_activity_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    status             TEXT NOT NULL DEFAULT 'active'
                     CHECK (status IN ('active', 'merged', 'closed', 'archived')),
    metadata           JSONB NOT NULL DEFAULT '{}'::jsonb,
    INDEX idx_session_branches_parent_session_id (parent_session_id),
    INDEX idx_session_branches_status (status),
    INDEX idx_session_branches_created_at (created_at)
);

-- Branch turns: tracks turns specific to branches for efficient querying
CREATE TABLE IF NOT EXISTS branch_turns (
    turn_id           BIGSERIAL PRIMARY KEY,
    branch_id         TEXT NOT NULL REFERENCES session_branches (branch_id) ON DELETE CASCADE,
    original_turn_id  BIGINT,  -- References the original turn in parent session if copied
    turn_number       INTEGER NOT NULL,
    messages          JSONB NOT NULL DEFAULT '[]'::jsonb,
    tool_calls        JSONB NOT NULL DEFAULT '[]'::jsonb,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    metadata          JSONB NOT NULL DEFAULT '{}'::jsonb,
    UNIQUE (branch_id, turn_number),
    INDEX idx_branch_turns_branch_id (branch_id),
    INDEX idx_branch_turns_turn_number (branch_id, turn_number)
);

-- Merge history: tracks all merge operations for audit and recovery
CREATE TABLE IF NOT EXISTS merge_history (
    merge_id          BIGSERIAL PRIMARY KEY,
    target_session_id TEXT NOT NULL REFERENCES sessions (session_id) ON DELETE CASCADE,
    source_session_id TEXT NOT NULL REFERENCES session_branches (branch_id) ON DELETE CASCADE,
    merge_strategy    TEXT NOT NULL,
    conflict_resolution TEXT NOT NULL,
    merged_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    merged_turns_count INTEGER NOT NULL DEFAULT 0,
    metadata          JSONB NOT NULL DEFAULT '{}'::jsonb,
    INDEX idx_merge_history_target_session_id (target_session_id),
    INDEX idx_merge_history_source_session_id (source_session_id),
    INDEX idx_merge_history_merged_at (merged_at)
);

-- Branch-specific indexes for performance optimization
CREATE INDEX IF NOT EXISTS idx_session_branches_parent_turn_id ON session_branches (parent_turn_id);
CREATE INDEX IF NOT EXISTS idx_branch_turns_original_turn_id ON branch_turns (original_turn_id);
CREATE INDEX IF NOT EXISTS idx_merge_history_merge_strategy ON merge_history (merge_strategy);
