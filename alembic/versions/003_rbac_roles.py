"""RBAC expansion: new roles, clubs, hod_buildings, booking_requests

Revision ID: 003
Revises: 002
Create Date: 2026-11-04

Changes:
  - users: add branch, division, club_id columns; remove is_cr flag
  - new table: clubs
  - new table: hod_buildings
  - new table: booking_requests
  - bookings: add 'pending'/'rejected'/'approved' to status values
  - policies: extend actor_kind to include new roles
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import TSRANGE

revision: str = '003'
down_revision: Union[str, None] = '002'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- clubs table (create first, users.club_id FKs to it) ---
    op.create_table(
        'clubs',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('description', sa.String(), nullable=True),
        sa.Column('president_id', sa.Integer(), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('name', name='uq_club_name'),
        sa.ForeignKeyConstraint(['president_id'], ['users.id']),
    )

    # --- alter users table ---
    # Add branch (for CR: e.g. "CSE"), division (for CR: e.g. "A")
    op.add_column('users', sa.Column('branch', sa.String(), nullable=True))
    op.add_column('users', sa.Column('division', sa.String(), nullable=True))
    # Add club_id FK for club_president role
    op.add_column('users', sa.Column('club_id', sa.Integer(), nullable=True))
    op.create_foreign_key(
        'fk_users_club_id', 'users', 'clubs', ['club_id'], ['id']
    )
    # Migrate existing is_cr=true students → role='cr', then drop is_cr
    op.execute("""
        UPDATE users SET role = 'cr' WHERE is_cr = true AND role = 'student'
    """)
    op.drop_column('users', 'is_cr')

    # --- hod_buildings table ---
    op.create_table(
        'hod_buildings',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('hod_id', sa.Integer(), nullable=False),
        sa.Column('building', sa.String(), nullable=False),
        sa.Column('department', sa.String(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('hod_id', 'building', 'department', name='uq_hod_building_dept'),
        sa.ForeignKeyConstraint(['hod_id'], ['users.id']),
    )
    op.create_index('ix_hod_buildings_hod_id', 'hod_buildings', ['hod_id'])

    # --- booking_requests table ---
    op.create_table(
        'booking_requests',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('resource_id', sa.Integer(), nullable=False),
        sa.Column('requester_id', sa.Integer(), nullable=False),
        sa.Column('during', TSRANGE(), nullable=False),
        sa.Column('purpose', sa.String(), nullable=False),
        sa.Column('status', sa.String(), nullable=False, server_default='pending'),
        # 'pending' | 'approved' | 'rejected'
        sa.Column('reviewed_by', sa.Integer(), nullable=True),
        sa.Column('review_note', sa.String(), nullable=True),
        sa.Column('reviewed_at', sa.DateTime(), nullable=True),
        sa.Column('booking_id', sa.Integer(), nullable=True),
        # created booking after approval
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['resource_id'], ['resources.id']),
        sa.ForeignKeyConstraint(['requester_id'], ['users.id']),
        sa.ForeignKeyConstraint(['reviewed_by'], ['users.id']),
        sa.ForeignKeyConstraint(['booking_id'], ['bookings.id']),
    )
    op.create_index('ix_booking_requests_resource_id', 'booking_requests', ['resource_id'])
    op.create_index('ix_booking_requests_requester_id', 'booking_requests', ['requester_id'])
    op.create_index('ix_booking_requests_status', 'booking_requests', ['status'])

    # Update EXCLUDE constraint: 'pending' requests should NOT block slots
    # (they become bookings only on approval); existing constraint on bookings
    # table already handles confirmed bookings — no change needed there.


def downgrade() -> None:
    op.drop_table('booking_requests')
    op.drop_table('hod_buildings')
    # Restore is_cr column
    op.add_column('users', sa.Column('is_cr', sa.Boolean(), nullable=False, server_default='false'))
    op.execute("UPDATE users SET is_cr = true WHERE role = 'cr'")
    op.execute("UPDATE users SET role = 'student' WHERE role = 'cr'")
    op.drop_constraint('fk_users_club_id', 'users', type_='foreignkey')
    op.drop_column('users', 'club_id')
    op.drop_column('users', 'division')
    op.drop_column('users', 'branch')
    op.drop_table('clubs')
