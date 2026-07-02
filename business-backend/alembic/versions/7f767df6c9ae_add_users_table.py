"""add users table

Revision ID: 7f767df6c9ae
Revises: 622d0f7855b7
Create Date: 2026-06-30 18:15:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '7f767df6c9ae'
down_revision: Union[str, None] = '622d0f7855b7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'users',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('username', sa.String(100), nullable=False),
        sa.Column('email', sa.String(255), nullable=False),
        sa.Column('hashed_password', sa.String(255), nullable=False),
        sa.Column('role', sa.Enum('ADMIN', 'MANAGER', 'OPERATOR',
                  name='user_role_enum', create_constraint=True),
                  nullable=False, index=True),
        sa.Column('is_active', sa.Boolean(), nullable=False,
                  server_default=sa.text('true')),
        sa.Column('created_at', sa.DateTime(timezone=True),
                  server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True),
                  server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_users_username', 'users', ['username'], unique=True)
    op.create_index('ix_users_email', 'users', ['email'], unique=True)


def downgrade() -> None:
    op.drop_index('ix_users_email', table_name='users')
    op.drop_index('ix_users_username', table_name='users')
    op.drop_table('users')
    op.execute('DROP TYPE IF EXISTS user_role_enum')
