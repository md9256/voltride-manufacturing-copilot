"""Cached AI daily production summaries.

Revision ID: 0003
Revises: 0002
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None

JSON = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def upgrade() -> None:
    op.create_table(
        "production_summaries",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("day", sa.String(10), nullable=False),
        sa.Column("language", sa.String(8), nullable=False),
        sa.Column("facts_hash", sa.String(64), nullable=False),
        sa.Column("facts", JSON, nullable=False),
        sa.Column("text", sa.Text, nullable=False),
        sa.Column("unverified", JSON, nullable=False),
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column("model", sa.String(100), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("day", "language", "facts_hash"),
    )
    op.create_index("ix_production_summaries_created_at", "production_summaries", ["created_at"])


def downgrade() -> None:
    op.drop_table("production_summaries")
