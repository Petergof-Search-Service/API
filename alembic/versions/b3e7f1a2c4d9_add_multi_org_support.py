"""add_multi_org_support

Revision ID: b3e7f1a2c4d9
Revises: 964d0e2ec9a1
Create Date: 2026-04-26 12:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "b3e7f1a2c4d9"
down_revision: Union[str, None] = "964d0e2ec9a1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "organizations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(), nullable=False, unique=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )

    op.create_table(
        "user_organizations",
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "org_id",
            sa.Integer(),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("role", sa.String(), nullable=False),
    )

    op.create_table(
        "indexes",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "org_id",
            sa.Integer(),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("vector_store_id", sa.String(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )

    op.add_column(
        "files",
        sa.Column(
            "org_id",
            sa.Integer(),
            sa.ForeignKey("organizations.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )

    # Seed: create "petergof" org and enrol all existing users
    conn = op.get_bind()

    conn.execute(sa.text("INSERT INTO organizations (name) VALUES ('petergof')"))
    org_id = conn.execute(
        sa.text("SELECT id FROM organizations WHERE name = 'petergof'")
    ).scalar()

    # is_admin=True → 'admin', else → 'user'
    conn.execute(
        sa.text(
            """
            INSERT INTO user_organizations (user_id, org_id, role)
            SELECT id, :org_id,
                   CASE WHEN is_admin THEN 'admin' ELSE 'user' END
            FROM users
            """
        ),
        {"org_id": org_id},
    )

    # Attach all existing files to petergof
    conn.execute(
        sa.text("UPDATE files SET org_id = :org_id WHERE org_id IS NULL"),
        {"org_id": org_id},
    )


def downgrade() -> None:
    op.drop_column("files", "org_id")
    op.drop_table("indexes")
    op.drop_table("user_organizations")
    op.drop_table("organizations")
