"""btree_gist extension and conflict lab demo tables

Revision ID: 001
Revises:
Create Date: 2026-10-10
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import TSRANGE

revision: str = '001'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS btree_gist")

    # demo_naive: no constraint, race conditions possible
    op.create_table(
        'demo_naive',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('room', sa.String(), nullable=False),
        sa.Column('during', TSRANGE(), nullable=False),
        sa.Column('who', sa.String(), nullable=False),
        sa.PrimaryKeyConstraint('id')
    )

    # demo_protected: EXCLUDE constraint prevents overlapping bookings
    op.create_table(
        'demo_protected',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('room', sa.String(), nullable=False),
        sa.Column('during', TSRANGE(), nullable=False),
        sa.Column('who', sa.String(), nullable=False),
        sa.PrimaryKeyConstraint('id')
    )
    op.execute("""
        ALTER TABLE demo_protected
        ADD CONSTRAINT demo_protected_no_overlap
        EXCLUDE USING gist (room WITH =, during WITH &&)
    """)


def downgrade() -> None:
    op.drop_table('demo_protected')
    op.drop_table('demo_naive')
    op.execute("DROP EXTENSION IF EXISTS btree_gist")
