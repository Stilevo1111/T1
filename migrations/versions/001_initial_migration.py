"""Initial migration

Revision ID: 001_initial_migration
Revises: 
Create Date: 2026-01-30 00:05:40.123456

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '001_initial_migration'
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    # Create users table if it doesn't exist
    op.create_table(
        'users',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('telegram_id', sa.BigInteger(), unique=True, nullable=False),
        sa.Column('username', sa.String(255), nullable=True),
        sa.Column('fissure', sa.Float(), default=0.1),
        sa.Column('last_fissure', sa.Float(), default=0.0),
        sa.CheckConstraint('telegram_id > 0', name='check_telegram_id_positive')
    )


def downgrade():
    # Drop users table
    op.drop_table('users')
