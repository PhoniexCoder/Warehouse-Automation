"""Add count_line column to cameras table

Revision ID: b9f2e8c1d4a7
Revises: a3c1d2e4f5b6
Create Date: 2026-07-31
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSON


revision: str = "b9f2e8c1d4a7"
down_revision: Union[str, None] = "c1a2b3d4e5f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "cameras",
        sa.Column("count_line", JSON, nullable=True),
    )


def downgrade() -> None:
    op.drop_column("cameras", "count_line")
