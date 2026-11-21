-- B-09 branch tables (A-11 wrapper reads this file on upgrade).
-- The original 20241107_b09_branch_schema.* pair was alembic Python saved
-- with a .sql extension and was never wired into the revision chain; this
-- rewrite is valid PostgreSQL and mirrors app/db/schema.sql.

CREATE TABLE IF NOT EXISTS session_branches (
    branch_id          TEXT PRIMARY KEY,
    parent_session_id  TEXT NOT NULL REFERENCES sessions (session_id) ON DELETE CASCADE,
    parent_turn_id     TEXT,
    branch_name        TEXT NOT NULL,
    created_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_activity_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    status             TEXT NOT NULL DEFAULT 'active'
                     CHECK (status IN ('active', 'merged', 'closed', 'archived')),
    metadata           JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE INDEX IF NOT EXISTS idx_session_branches_parent_session_id ON session_branches (parent_session_id);
CREATE INDEX IF NOT EXISTS idx_session_branches_status ON session_branches (status);
CREATE INDEX IF NOT EXISTS idx_session_branches_created_at ON session_branches (created_at);
CREATE INDEX IF NOT EXISTS idx_session_branches_parent_turn_id ON session_branches (parent_turn_id);

CREATE TABLE IF NOT EXISTS branch_turns (
    turn_id           BIGSERIAL PRIMARY KEY,
    branch_id         TEXT NOT NULL REFERENCES session_branches (branch_id) ON DELETE CASCADE,
    original_turn_id  BIGINT,
    turn_number       INTEGER NOT NULL,
    messages          JSONB NOT NULL DEFAULT '[]'::jsonb,
    tool_calls        JSONB NOT NULL DEFAULT '[]'::jsonb,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    metadata          JSONB NOT NULL DEFAULT '{}'::jsonb,
    UNIQUE (branch_id, turn_number)
);

CREATE INDEX IF NOT EXISTS idx_branch_turns_branch_id ON branch_turns (branch_id);
CREATE INDEX IF NOT EXISTS idx_branch_turns_turn_number ON branch_turns (branch_id, turn_number);
CREATE INDEX IF NOT EXISTS idx_branch_turns_original_turn_id ON branch_turns (original_turn_id);

CREATE TABLE IF NOT EXISTS merge_history (
    merge_id            BIGSERIAL PRIMARY KEY,
    target_session_id   TEXT NOT NULL REFERENCES sessions (session_id) ON DELETE CASCADE,
    source_session_id   TEXT NOT NULL REFERENCES session_branches (branch_id) ON DELETE CASCADE,
    merge_strategy      TEXT NOT NULL,
    conflict_resolution TEXT NOT NULL,
    merged_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
    merged_turns_count  INTEGER NOT NULL DEFAULT 0,
    metadata            JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE INDEX IF NOT EXISTS idx_merge_history_target_session_id ON merge_history (target_session_id);
CREATE INDEX IF NOT EXISTS idx_merge_history_source_session_id ON merge_history (source_session_id);
CREATE INDEX IF NOT EXISTS idx_merge_history_merged_at ON merge_history (merged_at);
CREATE INDEX IF NOT EXISTS idx_merge_history_merge_strategy ON merge_history (merge_strategy);
