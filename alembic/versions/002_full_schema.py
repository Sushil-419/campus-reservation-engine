"""Full application schema

Revision ID: 002
Revises: 001
Create Date: 2026-10-10
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import TSRANGE

revision: str = '002'
down_revision: Union[str, None] = '001'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- users ---
    op.create_table(
        'users',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('email', sa.String(), nullable=False),
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('password_hash', sa.String(), nullable=False),
        sa.Column('role', sa.String(), nullable=False),
        sa.Column('is_cr', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('department', sa.String(), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('email'),
    )
    op.create_index('ix_users_email', 'users', ['email'])

    # --- sessions ---
    op.create_table(
        'sessions',
        sa.Column('token_hash', sa.String(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.Column('expires_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
        sa.PrimaryKeyConstraint('token_hash'),
    )
    op.create_index('ix_sessions_user_id', 'sessions', ['user_id'])

    # --- resources ---
    op.create_table(
        'resources',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('building', sa.String(), nullable=False),
        sa.Column('floor', sa.Integer(), nullable=False),
        sa.Column('type', sa.String(), nullable=False),
        sa.Column('department', sa.String(), nullable=True),
        sa.Column('capacity', sa.Integer(), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default='true'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('building', 'name', name='uq_resource_building_name'),
    )

    # --- policies ---
    op.create_table(
        'policies',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('resource_type', sa.String(), nullable=False),
        sa.Column('actor_kind', sa.String(), nullable=False),
        sa.Column('allowed', sa.Boolean(), nullable=False),
        sa.Column('condition', sa.String(), nullable=False),
        sa.Column('max_minutes', sa.Integer(), nullable=False),
        sa.Column('max_advance_days', sa.Integer(), nullable=False),
        sa.Column('quota_active', sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('resource_type', 'actor_kind', name='uq_policy_type_actor'),
    )

    # --- bookings ---
    op.create_table(
        'bookings',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('resource_id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('during', TSRANGE(), nullable=False),
        sa.Column('source', sa.String(), nullable=False, server_default='user'),
        sa.Column('status', sa.String(), nullable=False, server_default='confirmed'),
        sa.Column('purpose', sa.String(), nullable=True),
        sa.Column('faculty_ref_id', sa.Integer(), nullable=True),
        sa.Column('course', sa.String(), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.Column('cancelled_at', sa.DateTime(), nullable=True),
        sa.Column('cancelled_by', sa.Integer(), nullable=True),
        sa.Column('cancel_reason', sa.String(), nullable=True),
        sa.ForeignKeyConstraint(['resource_id'], ['resources.id']),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
        sa.ForeignKeyConstraint(['faculty_ref_id'], ['users.id']),
        sa.ForeignKeyConstraint(['cancelled_by'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_bookings_resource_id', 'bookings', ['resource_id'])
    op.create_index('ix_bookings_user_id', 'bookings', ['user_id'])

    # EXCLUDE constraint: DB-level mutual exclusion for confirmed bookings
    op.execute("""
        ALTER TABLE bookings
        ADD CONSTRAINT bookings_no_overlap
        EXCLUDE USING gist (
            resource_id WITH =,
            during WITH &&
        ) WHERE (status = 'confirmed')
    """)

    # --- terms ---
    op.create_table(
        'terms',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('start_date', sa.Date(), nullable=False),
        sa.Column('end_date', sa.Date(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('name'),
    )

    # --- calendar_exceptions ---
    op.create_table(
        'calendar_exceptions',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('date', sa.Date(), nullable=False),
        sa.Column('reason', sa.String(), nullable=False),
        sa.Column('is_holiday', sa.Boolean(), nullable=False, server_default='true'),
        sa.PrimaryKeyConstraint('id'),
    )

    # --- timetable_slots ---
    op.create_table(
        'timetable_slots',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('term_id', sa.Integer(), nullable=False),
        sa.Column('weekday', sa.Integer(), nullable=False),
        sa.Column('start_time', sa.Time(), nullable=False),
        sa.Column('end_time', sa.Time(), nullable=False),
        sa.Column('resource_id', sa.Integer(), nullable=False),
        sa.Column('course', sa.String(), nullable=True),
        sa.Column('faculty_id', sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(['term_id'], ['terms.id']),
        sa.ForeignKeyConstraint(['resource_id'], ['resources.id']),
        sa.ForeignKeyConstraint(['faculty_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
    )

    # --- audit_log ---
    op.create_table(
        'audit_log',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.Column('actor_id', sa.Integer(), nullable=True),
        sa.Column('action', sa.String(), nullable=False),
        sa.Column('entity', sa.String(), nullable=False),
        sa.Column('entity_id', sa.Integer(), nullable=True),
        sa.Column('outcome', sa.String(), nullable=False),
        sa.Column('detail', sa.JSON(), nullable=True),
        sa.ForeignKeyConstraint(['actor_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
    )


def downgrade() -> None:
    op.drop_table('audit_log')
    op.drop_table('timetable_slots')
    op.drop_table('calendar_exceptions')
    op.drop_table('terms')
    op.drop_table('bookings')
    op.drop_table('policies')
    op.drop_table('resources')
    op.drop_table('sessions')
    op.drop_table('users')
