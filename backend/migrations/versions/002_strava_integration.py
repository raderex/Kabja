"""002_strava_integration

Revision ID: 002
Revises: 001
Create Date: 2026-06-09
"""
from alembic import op
import sqlalchemy as sa

revision = '002'
down_revision = '001'
branch_labels = None
depends_on = None


def upgrade():
    # Add Strava columns to users table
    op.add_column('users', sa.Column('strava_athlete_id', sa.BigInteger, nullable=True, unique=True))
    op.add_column('users', sa.Column('strava_access_token', sa.Text, nullable=True))
    op.add_column('users', sa.Column('strava_refresh_token', sa.Text, nullable=True))
    op.add_column('users', sa.Column('strava_token_expires_at', sa.BigInteger, nullable=True))
    op.add_column('users', sa.Column('strava_scope', sa.Text, nullable=True))
    op.add_column('users', sa.Column('strava_connected_at', sa.TIMESTAMP(timezone=True), nullable=True))
    op.add_column('users', sa.Column('strava_profile', sa.Text, nullable=True)) # JSON blob

    # Track which Strava activities have already been imported
    op.create_table(
        'strava_imported_activities',
        sa.Column('strava_activity_id', sa.BigInteger, primary_key=True),
        sa.Column('user_id', sa.Text, sa.ForeignKey('users.id'), nullable=False),
        sa.Column('run_id', sa.Text, sa.ForeignKey('runs.id'), nullable=True),
        sa.Column('activity_name', sa.Text),
        sa.Column('activity_type', sa.Text),
        sa.Column('distance_km', sa.Float),
        sa.Column('moving_time_s', sa.Integer),
        sa.Column('start_date', sa.TIMESTAMP(timezone=True)),
        sa.Column('imported_at', sa.TIMESTAMP(timezone=True), server_default=sa.func.now()),
    )
    op.create_index('idx_strava_imported_user', 'strava_imported_activities', ['user_id'])

    # Add source column to runs table to distinguish Kabja-native vs Strava-imported
    op.add_column('runs', sa.Column('source', sa.Text, server_default='kabja'))
    op.add_column('runs', sa.Column('strava_activity_id', sa.BigInteger, nullable=True))


def downgrade():
    op.drop_column('runs', 'strava_activity_id')
    op.drop_column('runs', 'source')
    op.drop_index('idx_strava_imported_user', 'strava_imported_activities')
    op.drop_table('strava_imported_activities')
    op.drop_column('users', 'strava_profile')
    op.drop_column('users', 'strava_connected_at')
    op.drop_column('users', 'strava_scope')
    op.drop_column('users', 'strava_token_expires_at')
    op.drop_column('users', 'strava_refresh_token')
    op.drop_column('users', 'strava_access_token')
    op.drop_column('users', 'strava_athlete_id')