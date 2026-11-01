-- audit_events_hot table: security audit events for hot tier
--
-- Same INVARIANT as eval_results_hot (PC21): the hot TTL must outlast the cron
-- archive trigger (AGENT_OBS_CRON_AUDIT_RETENTION_DAYS, default 365d), or
-- ClickHouse deletes the rows before cleanup_audit_events.py can ship them to
-- S3 Parquet. 400d leaves a 35-day window. The cold bucket then keeps each
-- object for 365 days from upload, so total audit retention stays well above
-- the 1-year minimum required by ARCHITECT.md 3.4.
CREATE DATABASE IF NOT EXISTS observability;

CREATE TABLE IF NOT EXISTS observability.audit_events_hot (
    audit_id String,
    timestamp DateTime64(3),
    trace_id String,
    actor JSON,
    action String,
    decision String,
    resource JSON,
    reason String,
    ip_address String,
    user_agent String,
    created_at DateTime64(3) DEFAULT now()
)
ENGINE = MergeTree()
ORDER BY (timestamp, audit_id)
PARTITION BY toYYYYMMDD(timestamp)
TTL timestamp + INTERVAL 400 DAY
SETTINGS index_granularity = 8192;