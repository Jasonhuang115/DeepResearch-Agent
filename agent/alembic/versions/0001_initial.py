"""Create the six-table schema.

Revision ID: 0001_initial
Revises:
"""

import sqlalchemy as sa
from sqlalchemy.dialects import mysql

from alembic import op

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.CHAR(26), primary_key=True),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("created_at", mysql.DATETIME(fsp=3), nullable=False),
        mysql_engine="InnoDB",
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_0900_ai_ci",
    )
    op.create_index("uk_users_email", "users", ["email"], unique=True)

    op.create_table(
        "conversations",
        sa.Column("id", sa.CHAR(26), primary_key=True),
        sa.Column("user_id", sa.CHAR(26), nullable=False),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("created_at", mysql.DATETIME(fsp=3), nullable=False),
        sa.Column("updated_at", mysql.DATETIME(fsp=3), nullable=False),
        sa.Column("deleted_at", mysql.DATETIME(fsp=3), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        mysql_engine="InnoDB",
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_0900_ai_ci",
    )
    op.create_index(
        "idx_conv_user_updated",
        "conversations",
        ["user_id", "deleted_at", "updated_at", "id"],
    )

    op.create_table(
        "runs",
        sa.Column("id", sa.CHAR(26), primary_key=True),
        sa.Column("conversation_id", sa.CHAR(26), nullable=False),
        sa.Column("idempotency_key", sa.String(64), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("lease_expires_at", mysql.DATETIME(fsp=3), nullable=True),
        sa.Column(
            "attempt_count", mysql.TINYINT(unsigned=True), nullable=False, server_default="0"
        ),
        sa.Column("created_at", mysql.DATETIME(fsp=3), nullable=False),
        sa.CheckConstraint("attempt_count <= 2", name="ck_run_attempt_count"),
        sa.CheckConstraint(
            "status IN ('queued','running','cancelling','succeeded','failed','cancelled')",
            name="ck_run_status",
        ),
        sa.ForeignKeyConstraint(["conversation_id"], ["conversations.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("conversation_id", "idempotency_key", name="uk_run_idempotency"),
        mysql_engine="InnoDB",
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_0900_ai_ci",
    )
    op.create_index("idx_run_queue", "runs", ["status", "lease_expires_at", "created_at"])
    op.create_index("idx_run_conv_status", "runs", ["conversation_id", "status"])
    op.create_index("idx_run_conv_time", "runs", ["conversation_id", "created_at", "id"])

    op.create_table(
        "messages",
        sa.Column("id", sa.CHAR(26), primary_key=True),
        sa.Column("run_id", sa.CHAR(26), nullable=False),
        sa.Column("role", sa.String(16), nullable=False),
        sa.Column("content", mysql.MEDIUMTEXT(), nullable=False),
        sa.Column("created_at", mysql.DATETIME(fsp=3), nullable=False),
        sa.CheckConstraint("role IN ('user','assistant')", name="ck_message_role"),
        sa.ForeignKeyConstraint(["run_id"], ["runs.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("run_id", "role", name="uk_message_run_role"),
        mysql_engine="InnoDB",
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_0900_ai_ci",
    )

    op.create_table(
        "attachments",
        sa.Column("id", sa.CHAR(26), primary_key=True),
        sa.Column("message_id", sa.CHAR(26), nullable=False),
        sa.Column("filename", sa.String(255), nullable=False),
        sa.Column("content_type", sa.String(127), nullable=False),
        sa.Column("size_bytes", mysql.BIGINT(unsigned=True), nullable=False),
        sa.CheckConstraint("size_bytes > 0", name="ck_attachment_size"),
        sa.ForeignKeyConstraint(["message_id"], ["messages.id"], ondelete="CASCADE"),
        mysql_engine="InnoDB",
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_0900_ai_ci",
    )
    op.create_index("idx_attachment_message", "attachments", ["message_id"])

    op.create_table(
        "run_events",
        sa.Column("run_id", sa.CHAR(26), primary_key=True),
        sa.Column("seq", mysql.INTEGER(unsigned=True), primary_key=True),
        sa.Column("type", sa.String(32), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("created_at", mysql.DATETIME(fsp=3), nullable=False),
        sa.CheckConstraint("seq > 0", name="ck_run_event_seq"),
        sa.ForeignKeyConstraint(["run_id"], ["runs.id"], ondelete="CASCADE"),
        mysql_engine="InnoDB",
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_0900_ai_ci",
    )


def downgrade() -> None:
    op.drop_table("run_events")
    op.drop_table("attachments")
    op.drop_table("messages")
    op.drop_table("runs")
    op.drop_table("conversations")
    op.drop_table("users")
