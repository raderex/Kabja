---
name: add_user_auth_fields
description: Add display_name, password_hash, password_salt, avatar_url, total_km2, total_runs, streak_days, last_run_date columns to users table
---
"""003_user_auth_fields

Revision ID: 003
Revises: 002
Create Date: 2026-06-02
"""
from alembic import op
import sqlalchemy as sa

revision = '003'
down_revision = '002'
branch_labels = None
depends_on = None

def upgrade():
    op.add_column('users', sa.Column('display_name', sa.Text, nullable=True))
    op.add_column('users', sa.Column('password_hash', sa.Text, nullable=True))
    op.add_column('users', sa.Column('password_salt', sa.Text, nullable=True))
    op.add_column('users', sa.Column('avatar_url', sa.Text, nullable=True))
    op.add_column('users', sa.Column('total_km2', sa.Float, server_default='0'))
    op.add_column('users', sa.Column('total_runs', sa.Integer, server_default='0'))
    op.add_column('users', sa.Column('streak_days', sa.Integer, server_default='0'))
    op.add_column('users', sa.Column('last_run_date', sa.Date, nullable=True))

def downgrade():
    for col in ['display_name','password_hash','password_salt','avatar_url','total_km2','total_runs','streak_days','last_run_date']:
        op.drop_column('users', col)
