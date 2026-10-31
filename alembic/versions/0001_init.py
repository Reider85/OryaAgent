"""0001_init: initial OryaAgent schema, wrapped as an Alembic revision (A-11).

The ``.sql`` file in ``app/db/migrations/`` stays the single source of truth
for the upgrade DDL (``tests/unit/test_db_schema.py`` checks schema.sql ↔
.sql drift; ``tests/unit/test_alembic.py`` checks .sql ↔ revision 1:1).
Downgrade is inline: indexes drop together with their tables.
"""

from __future__ import annotations

from alembic import op

# revision identifiers, used by Alembic.
revision = "0001_init"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    from app.db.migrate import MIGRATIONS_DIR

    op.execute((MIGRATIONS_DIR / "0001_init.sql").read_text(encoding="utf-8"))


def downgrade() -> None:
    # Reverse of 0001_init — all four tables, FK children before parents (A-11).
    op.execute("DROP TABLE IF EXISTS tool_calls")
    op.execute("DROP TABLE IF EXISTS messages")
    op.execute("DROP TABLE IF EXISTS memory_audit_log")
    op.execute("DROP TABLE IF EXISTS sessions")
