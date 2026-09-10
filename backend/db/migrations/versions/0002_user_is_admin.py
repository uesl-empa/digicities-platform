# SPDX-License-Identifier: Apache-2.0
"""users.is_admin: platform administrators (manage accounts, see all workspaces)

Revision ID: 0002_user_is_admin
Revises: 0001_initial
"""
from alembic import op
import sqlalchemy as sa

revision = "0002_user_is_admin"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("users", sa.Column("is_admin", sa.Boolean, server_default=sa.false()))


def downgrade():
    op.drop_column("users", "is_admin")
