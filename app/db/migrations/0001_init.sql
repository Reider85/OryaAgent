-- 0001_init: initial OryaAgent schema (M-03).
-- Keep in sync with app/db/schema.sql (canonical full state).

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
