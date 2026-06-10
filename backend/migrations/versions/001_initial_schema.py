"""001_initial_schema

Revision ID: 001
Revises: 
Create Date: 2026-06-02
"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '001'
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.execute('CREATE EXTENSION IF NOT EXISTS "pgcrypto"')

    op.create_table(
        'users',
        sa.Column('id', sa.Text, primary_key=True, server_default=sa.text("gen_random_uuid()::text")),
        sa.Column('username', sa.Text, unique=True, nullable=False),
        sa.Column('telegram_id', sa.Text, nullable=True),
        sa.Column('created_at', sa.TIMESTAMP(timezone=True), server_default=sa.func.now()),
    )

    op.create_table(
        'runs',
        sa.Column('id', sa.Text, primary_key=True, server_default=sa.text("gen_random_uuid()::text")),
        sa.Column('user_id', sa.Text, sa.ForeignKey('users.id'), nullable=False),
        sa.Column('started_at', sa.TIMESTAMP(timezone=True)),
        sa.Column('finished_at', sa.TIMESTAMP(timezone=True)),
        sa.Column('distance_km', sa.Float, default=0),
        sa.Column('polyline', sa.Text),
        sa.Column('snapped_polyline', sa.Text),
        sa.Column('status', sa.Text, default='active'),
    )

    op.create_table(
        'cells',
        sa.Column('h3_index', sa.Text, primary_key=True),
        sa.Column('owner_id', sa.Text, sa.ForeignKey('users.id')),
        sa.Column('captured_at', sa.TIMESTAMP(timezone=True), server_default=sa.func.now()),
        sa.Column('run_id', sa.Text, sa.ForeignKey('runs.id')),
    )
    op.create_index('idx_cells_owner', 'cells', ['owner_id'])

    op.create_table(
        'competitions',
        sa.Column('id', sa.Integer, primary_key=True, autoincrement=True),
        sa.Column('name', sa.Text),
        sa.Column('prize_description', sa.Text),
        sa.Column('prize_image_url', sa.Text),
        sa.Column('starts_at', sa.TIMESTAMP(timezone=True)),
        sa.Column('ends_at', sa.TIMESTAMP(timezone=True)),
        sa.Column('status', sa.Text, default='upcoming'),
    )

    op.create_table(
        'competition_entries',
        sa.Column('id', sa.Integer, primary_key=True, autoincrement=True),
        sa.Column('competition_id', sa.Integer, sa.ForeignKey('competitions.id')),
        sa.Column('user_id', sa.Text, sa.ForeignKey('users.id')),
        sa.Column('cell_count', sa.Integer),
        sa.Column('km2', sa.Float),
        sa.Column('created_at', sa.TIMESTAMP(timezone=True), server_default=sa.func.now()),
    )

    # Seed a demo competition
    op.execute("""
        INSERT INTO competitions (name, prize_description, prize_image_url, starts_at, ends_at, status)
        VALUES (
            'June Sprint',
            'Free month of premium membership',
            'https://placehold.co/400x300?text=Prize',
            now(),
            now() + interval '30 days',
            'active'
        )
    """)


def downgrade():
    op.drop_table('competition_entries')
    op.drop_table('competitions')
    op.drop_index('idx_cells_owner', 'cells')
    op.drop_table('cells')
    op.drop_table('runs')
    op.drop_table('users')
