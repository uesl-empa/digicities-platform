# SPDX-License-Identifier: Apache-2.0
"""initial schema: users, workspaces, workspace_acl

Revision ID: 0001_initial
Revises:
"""
from alembic import op
import sqlalchemy as sa

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "users",
        sa.Column("id", sa.String(255), primary_key=True),
        sa.Column("email", sa.String(320), nullable=False, unique=True),
        sa.Column("password_hash", sa.String(255)),
        sa.Column("display_name", sa.String(255), server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_users_email", "users", ["email"], unique=True)
    op.create_table(
        "workspaces",
        sa.Column("id", sa.String(255), primary_key=True),
        sa.Column("name", sa.String(512), server_default=""),
        sa.Column("owner_id", sa.String(255)),
        sa.Column("visibility", sa.String(16), server_default="shared"),
        sa.Column("backend", sa.String(32), server_default="local"),
        sa.Column("graphdb_repo", sa.String(255), server_default=""),
        sa.Column("description", sa.Text, server_default=""),
        sa.Column("tags", sa.Text, server_default="[]"),
        sa.Column("protected", sa.Boolean, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True)),
        sa.Column("updated_at", sa.DateTime(timezone=True)),
    )
    op.create_table(
        "workspace_acl",
        sa.Column("workspace_id", sa.String(255), primary_key=True),
        sa.Column("user_id", sa.String(255), primary_key=True),
        sa.Column("role", sa.String(16), server_default="editor"),
    )


def downgrade():
    op.drop_table("workspace_acl")
    op.drop_index("ix_users_email", table_name="users")
    op.drop_table("users")
    op.drop_table("workspaces")
