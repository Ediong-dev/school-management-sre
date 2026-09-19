"""add last_login column to users

Revision ID: 0002_add_last_login
Revises: 0001_baseline
Create Date: 2026-09-19
"""
from alembic import op
import sqlalchemy as sa

revision = "0002_add_last_login"
down_revision = "0001_baseline"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add a nullable column — safe for zero-downtime deployment.

    Nullable means existing rows don't violate any constraint. Adding it
    takes an ACCESS EXCLUSIVE lock only briefly (milliseconds), then
    releases. Reads and writes to other columns continue unaffected.
    """
    op.execute("""
        ALTER TABLE users
        ADD COLUMN IF NOT EXISTS last_login TIMESTAMPTZ
    """)


def downgrade() -> None:
    op.execute("ALTER TABLE users DROP COLUMN IF EXISTS last_login")