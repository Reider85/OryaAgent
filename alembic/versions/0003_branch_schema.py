"""0003_branch_schema: B-09 branch tables, wrapped for Alembic (A-11).

``session_branches`` / ``branch_turns`` / ``merge_history`` back
``BranchManager`` (B-09). The original ``20241107_b09_branch_schema`` pair
was alembic Python saved with a ``.sql`` extension and never joined the
revision chain — this wrapper supersedes it. Downgrade drops the three
tables (indexes go with them).
"""

from __future__ import annotations

from alembic import op

# revision identifiers, used by Alembic.
revision = "0003_branch_schema"
down_revision = "0002_session_log_encryption"
branch_labels = None
depends_on = None


def upgrade() -> None:
    from app.db.migrate import MIGRATIONS_DIR

    op.execute((MIGRATIONS_DIR / "0003_branch_schema.sql").read_text(encoding="utf-8"))


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS merge_history")
    op.execute("DROP TABLE IF EXISTS branch_turns")
    op.execute("DROP TABLE IF EXISTS session_branches")
