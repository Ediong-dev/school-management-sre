"""SIMULATE a bad migration — hold ACCESS EXCLUSIVE lock on users

Revision ID: 0003_bad_lock_add_column
Revises: 0002_add_last_login
Create Date: 2026-09-19

WARNING: This migration is intentionally bad. It holds an ACCESS EXCLUSIVE
lock on the users table for ~10 seconds. Every SELECT, INSERT, UPDATE, or
DELETE against users — including the /login query — will block until the
lock is released. If the client has a timeout shorter than the lock
duration, users see errors.

This is what happens in production when someone runs:
    ALTER TABLE users ADD COLUMN new_col TYPE NOT NULL DEFAULT 'x';
on a table large enough that the rewrite takes seconds. Postgres 11+
optimizes some cases, but adding a NOT NULL column with a non-constant
default still rewrites the table.
"""
from alembic import op
import sqlalchemy as sa

revision = "0003_bad_lock_add_column"
down_revision = "0002_add_last_login"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Simulate a table-rewriting operation by holding a lock.
    op.execute("LOCK TABLE users IN ACCESS EXCLUSIVE MODE")
    op.execute("SELECT pg_sleep(10)")
    # The actual change: a nullable column (safe on its own).
    op.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS email_verified BOOLEAN")


def downgrade() -> None:
    op.execute("ALTER TABLE users DROP COLUMN IF EXISTS email_verified")