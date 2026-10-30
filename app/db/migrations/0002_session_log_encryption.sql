-- 0002_session_log_encryption: pgcrypto for session-log encryption at rest (A-05).
-- Keep in sync with app/db/schema.sql (canonical full state).
--
-- pgcrypto provides pgp_sym_encrypt/pgp_sym_decrypt used by
-- app/db/session_log.py when ORYA_SESSION_LOG_ENCRYPTION_ENABLED=true.
-- The extension itself is created unconditionally (idempotent, IF NOT
-- EXISTS) so the feature can be switched on later without re-running
-- migrations; actual encryption is decided per-query by the app seam.

CREATE EXTENSION IF NOT EXISTS pgcrypto;
