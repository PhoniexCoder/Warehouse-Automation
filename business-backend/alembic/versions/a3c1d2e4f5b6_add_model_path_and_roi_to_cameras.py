"""Add model_path and roi columns to cameras table

Revision ID: a3c1d2e4f5b6
Revises: 7f767df6c9ae
Create Date: 2026-07-18
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSON


revision: str = "a3c1d2e4f5b6"
down_revision: Union[str, None] = "7f767df6c9ae"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "cameras",
        sa.Column("model_path", sa.String(500), nullable=True),
    )
    op.add_column(
        "cameras",
        sa.Column("roi", JSON, nullable=True),
    )


def downgrade() -> None:
    op.drop_column("cameras", "roi")
    op.drop_column("cameras", "model_path")
