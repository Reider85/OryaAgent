"""Add branch-specific tables for B-09 functionality.

Revision ID: 20241107_b09_branch_schema
Revises: 20241107_base
Create Date: 2024-11-07 14:44:00.000000

"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '20241107_b09_branch_schema'
down_revision = '20241107_base'
branch_labels = None
depends_on = None


def upgrade():
    """Add branch-specific tables to the database schema."""
    
    # Sessions branches: tracks parent-child relationships and branch metadata
    op.create_table(
        'session_branches',
        sa.Column('branch_id', sa.Text(), nullable=False),
        sa.Column('parent_session_id', sa.Text(), nullable=False),
        sa.Column('parent_turn_id', sa.Text(), nullable=True),
        sa.Column('branch_name', sa.Text(), nullable=False),
        sa.Column('created_at', sa.TIMESTAMP(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('last_activity_at', sa.TIMESTAMP(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('status', sa.Text(), server_default='active', nullable=False),
        sa.Column('metadata', postgresql.JSONB(), server_default="'{}'::jsonb", nullable=False),
        sa.ForeignKeyConstraint(['parent_session_id'], ['sessions.session_id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('branch_id')
    )
    
    op.create_index(
        'idx_session_branches_parent_session_id',
        'session_branches',
        ['parent_session_id']
    )
    
    op.create_index(
        'idx_session_branches_status',
        'session_branches',
        ['status']
    )
    
    op.create_index(
        'idx_session_branches_created_at',
        'session_branches',
        ['created_at']
    )
    
    op.create_index(
        'idx_session_branches_parent_turn_id',
        'session_branches',
        ['parent_turn_id']
    )
    
    # Branch turns: tracks turns specific to branches for efficient querying
    op.create_table(
        'branch_turns',
        sa.Column('turn_id', sa.BigInteger(), nullable=False),
        sa.Column('branch_id', sa.Text(), nullable=False),
        sa.Column('original_turn_id', sa.BigInteger(), nullable=True),
        sa.Column('turn_number', sa.Integer(), nullable=False),
        sa.Column('messages', postgresql.JSONB(), server_default="'[]'::jsonb", nullable=False),
        sa.Column('tool_calls', postgresql.JSONB(), server_default="'[]'::jsonb", nullable=False),
        sa.Column('created_at', sa.TIMESTAMP(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('metadata', postgresql.JSONB(), server_default="'{}'::jsonb", nullable=False),
        sa.ForeignKeyConstraint(['branch_id'], ['session_branches.branch_id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('turn_id'),
        sa.UniqueConstraint('branch_id', 'turn_name')
    )
    
    op.create_index(
        'idx_branch_turns_branch_id',
        'branch_turns',
        ['branch_id']
    )
    
    op.create_index(
        'idx_branch_turns_turn_number',
        'branch_turns',
        ['branch_id', 'turn_number']
    )
    
    op.create_index(
        'idx_branch_turns_original_turn_id',
        'branch_turns',
        ['original_turn_id']
    )
    
    # Merge history: tracks all merge operations for audit and recovery
    op.create_table(
        'merge_history',
        sa.Column('merge_id', sa.BigInteger(), nullable=False),
        sa.Column('target_session_id', sa.Text(), nullable=False),
        sa.Column('source_session_id', sa.Text(), nullable=False),
        sa.Column('merge_strategy', sa.Text(), nullable=False),
        sa.Column('conflict_resolution', sa.Text(), nullable=False),
        sa.Column('merged_at', sa.TIMESTAMP(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('merged_turns_count', sa.Integer(), server_default='0', nullable=False),
        sa.Column('metadata', postgresql.JSONB(), server_default="'{}'::jsonb", nullable=False),
        sa.ForeignKeyConstraint(['target_session_id'], ['sessions.session_id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['source_session_id'], ['session_branches.branch_id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('merge_id')
    )
    
    op.create_index(
        'idx_merge_history_target_session_id',
        'merge_history',
        ['target_session_id']
    )
    
    op.create_index(
        'idx_merge_history_source_session_id',
        'merge_history',
        ['source_session_id']
    )
    
    op.create_index(
        'idx_merge_history_merged_at',
        'merge_history',
        ['merged_at']
    )
    
    op.create_index(
        'idx_merge_history_merge_strategy',
        'merge_history',
        ['merge_strategy']
    )


def downgrade():
    """Remove branch-specific tables from the database schema."""
    
    # Drop indexes
    op.drop_index('idx_merge_history_merge_strategy', table_name='merge_history')
    op.drop_index('idx_merge_history_merged_at', table_name='merge_history')
    op.drop_index('idx_merge_history_source_session_id', table_name='merge_history')
    op.drop_index('idx_merge_history_target_session_id', table_name='merge_history')
    op.drop_index('idx_branch_turns_original_turn_id', table_name='branch_turns')
    op.drop_index('idx_branch_turns_turn_number', table_name='branch_turns')
    op.drop_index('idx_branch_turns_branch_id', table_name='branch_turns')
    op.drop_index('idx_session_branches_parent_turn_id', table_name='session_branches')
    op.drop_index('idx_session_branches_created_at', table_name='session_branches')
    op.drop_index('idx_session_branches_status', table_name='session_branches')
    op.drop_index('idx_session_branches_parent_session_id', table_name='session_branches')
    
    # Drop tables
    op.drop_table('merge_history')
    op.drop_table('branch_turns')
    op.drop_table('session_branches')