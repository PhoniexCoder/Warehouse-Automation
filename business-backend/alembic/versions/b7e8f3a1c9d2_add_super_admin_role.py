"""add super_admin role

Revision ID: b7e8f3a1c9d2
Revises: a3c1d2e4f5b6
Create Date: 2026-07-19 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'b7e8f3a1c9d2'
down_revision: Union[str, None] = 'a3c1d2e4f5b6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TYPE user_role_enum ADD VALUE IF NOT EXISTS 'SUPER_ADMIN'")


def downgrade() -> None:
    op.execute("DELETE FROM users WHERE role = 'SUPER_ADMIN'")
