"""0002_session_log_encryption: pgcrypto extension, wrapped for Alembic (A-11).

Feeds ``app/db/session_log.py`` (``pgp_sym_encrypt``/``pgp_sym_decrypt`` for
session-log encryption at rest, A-05). The extension itself is created
unconditionally and idempotently — actual encryption stays decided per-query
by ``ORYA_SESSION_LOG_ENCRYPTION_ENABLED``. Downgrade drops the extension
(the app references it only inside queries, so nothing persists).
"""

from __future__ import annotations

from alembic import op

# revision identifiers, used by Alembic.
revision = "0002_session_log_encryption"
down_revision = "0001_init"
branch_labels = None
depends_on = None


def upgrade() -> None:
    from app.db.migrate import MIGRATIONS_DIR

    op.execute(
        (MIGRATIONS_DIR / "0002_session_log_encryption.sql").read_text(encoding="utf-8")
    )


def downgrade() -> None:
    op.execute("DROP EXTENSION IF EXISTS pgcrypto")
