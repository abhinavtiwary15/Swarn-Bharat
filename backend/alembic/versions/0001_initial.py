"""0001_initial — pgvector extension + users table.

Revision ID: 0001
Revises: (none — initial migration)
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Install pgvector extension.  No Vector column is added to this table yet;
    # the extension is here so future migrations can add vector columns without
    # a separate extension step.
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.create_table(
        "users",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("email", sa.String(254), nullable=False),
        sa.Column("hashed_password", sa.String(), nullable=True),
        sa.Column("full_name", sa.String(200), nullable=False),
        sa.Column(
            "is_verified",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column("oauth_provider", sa.String(32), nullable=True),
        sa.Column("oauth_sub", sa.String(256), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )

    # Unique email index
    op.create_index("ix_users_email", "users", ["email"], unique=True)

    # Partial unique index: one (provider, sub) pair per row, NULLs excluded.
    # Prevents duplicate Google accounts; allows many password-only users (both NULL).
    op.create_index(
        "uix_users_oauth_sub",
        "users",
        ["oauth_provider", "oauth_sub"],
        unique=True,
        postgresql_where=sa.text("oauth_provider IS NOT NULL AND oauth_sub IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("uix_users_oauth_sub", table_name="users")
    op.drop_index("ix_users_email", table_name="users")
    op.drop_table("users")
    op.execute("DROP EXTENSION IF EXISTS vector")
