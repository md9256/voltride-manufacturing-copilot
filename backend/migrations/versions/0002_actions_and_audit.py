"""Proposed actions, quote reviews and the audit log.

Revision ID: 0002
Revises: 0001
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

JSON = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")
TS = sa.DateTime(timezone=True)


def upgrade() -> None:
    op.create_table(
        "proposed_actions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("owner_id", sa.String(64), nullable=False),
        sa.Column("conversation_id", sa.String(36), nullable=True),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("source", sa.String(32), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("payload", JSON, nullable=False),
        sa.Column("result", JSON, nullable=True),
        sa.Column("error", sa.Text, nullable=True),
        sa.Column("created_at", TS, nullable=False),
        sa.Column("expires_at", TS, nullable=False),
        sa.Column("decided_at", TS, nullable=True),
    )
    op.create_index("ix_proposed_actions_owner_id", "proposed_actions", ["owner_id"])
    op.create_index("ix_proposed_actions_status", "proposed_actions", ["status"])

    op.create_table(
        "quote_reviews",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("owner_id", sa.String(64), nullable=False),
        sa.Column("file_sha256", sa.String(64), nullable=False),
        sa.Column("filename", sa.String(255), nullable=False),
        sa.Column("extraction", JSON, nullable=False),
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column("model", sa.String(100), nullable=False),
        sa.Column("created_at", TS, nullable=False),
    )
    op.create_index("ix_quote_reviews_owner_id", "quote_reviews", ["owner_id"])
    op.create_index("ix_quote_reviews_file_sha256", "quote_reviews", ["file_sha256"])

    op.create_table(
        "audit_log",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("created_at", TS, nullable=False),
        sa.Column("owner_id", sa.String(64), nullable=True),
        sa.Column("conversation_id", sa.String(36), nullable=True),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("name", sa.String(64), nullable=False),
        sa.Column("question", sa.Text, nullable=True),
        sa.Column("params", JSON, nullable=True),
        sa.Column("result", JSON, nullable=True),
        sa.Column("ok", sa.Boolean, nullable=False),
        sa.Column("duration_ms", sa.Float, nullable=True),
        sa.Column("provider", sa.String(32), nullable=True),
        sa.Column("model", sa.String(100), nullable=True),
    )
    op.create_index("ix_audit_log_created_at", "audit_log", ["created_at"])
    op.create_index("ix_audit_log_conversation_id", "audit_log", ["conversation_id"])
    op.create_index("ix_audit_log_kind", "audit_log", ["kind"])


def downgrade() -> None:
    op.drop_table("audit_log")
    op.drop_table("quote_reviews")
    op.drop_table("proposed_actions")
