"""add nvrs table and cameras.nvr_id

Revision ID: c1a2b3d4e5f6
Revises: b7e8f3a1c9d2
Create Date: 2026-07-19 12:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID


revision: str = 'c1a2b3d4e5f6'
down_revision: Union[str, None] = 'b7e8f3a1c9d2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "nvrs",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("warehouse_id", UUID(as_uuid=True), sa.ForeignKey("warehouses.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("name", sa.String(255), nullable=False, index=True),
        sa.Column("ip_address", sa.String(45), nullable=False),
        sa.Column("port", sa.Integer, nullable=False, server_default="34567"),
        sa.Column("protocol", sa.String(20), nullable=False, server_default="dvrip"),
        sa.Column("username", sa.String(255), nullable=True),
        sa.Column("password", sa.String(255), nullable=True),
        sa.Column("is_tailscale", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("status", sa.String(20), nullable=False, server_default="active"),
        sa.Column("last_seen", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    op.add_column(
        "cameras",
        sa.Column("nvr_id", UUID(as_uuid=True), sa.ForeignKey("nvrs.id", ondelete="SET NULL"), nullable=True, index=True),
    )


def downgrade() -> None:
    op.drop_column("cameras", "nvr_id")
    op.drop_table("nvrs")
