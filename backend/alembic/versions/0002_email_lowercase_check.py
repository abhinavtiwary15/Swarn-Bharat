"""0002_email_lowercase_check — enforce lowercase email constraint.

Revision ID: 0002
Revises: 0001
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_check_constraint(
        "ck_users_email_lowercase",
        "users",
        "email = lower(email)",
    )


def downgrade() -> None:
    op.drop_constraint("ck_users_email_lowercase", "users", type_="check")
