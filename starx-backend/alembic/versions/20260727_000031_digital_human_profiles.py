"""增加数字人档案与外部任务持久化结构。"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260727_000031"
down_revision: str | None = "20260723_000030"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "digital_human_profiles",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("account_id", sa.String(length=36), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("source_video_storage_key", sa.Text(), nullable=False),
        sa.Column("source_video_url", sa.Text(), nullable=False),
        sa.Column("source_audio_storage_key", sa.Text(), nullable=False, server_default=""),
        sa.Column("source_audio_url", sa.Text(), nullable=False, server_default=""),
        sa.Column("cover_storage_key", sa.Text(), nullable=False, server_default=""),
        sa.Column("cover_url", sa.Text(), nullable=False, server_default=""),
        sa.Column("width", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("height", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("duration_seconds", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("training_script_version", sa.String(length=32), nullable=False),
        sa.Column("training_script_snapshot", sa.Text(), nullable=False),
        sa.Column("training_script_hash", sa.String(length=64), nullable=False),
        sa.Column("validation_report", sa.JSON(), nullable=False),
        sa.Column("voice_provider", sa.String(length=32), nullable=False),
        sa.Column("provider_voice_id", sa.String(length=255), nullable=False, server_default=""),
        sa.Column("voice_status", sa.String(length=32), nullable=False),
        sa.Column("voice_preview_storage_key", sa.Text(), nullable=False, server_default=""),
        sa.Column("voice_preview_url", sa.Text(), nullable=False, server_default=""),
        sa.Column("enrollment_workflow_id", sa.String(length=36), nullable=True),
        sa.Column("error_code", sa.String(length=64), nullable=False, server_default=""),
        sa.Column("error_message", sa.Text(), nullable=False, server_default=""),
        sa.Column("consent_version", sa.String(length=32), nullable=False),
        sa.Column("consent_confirmed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["enrollment_workflow_id"], ["workflows.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("id", "account_id", name="uq_digital_human_profile_account"),
    )
    for column in ("user_id", "account_id", "status", "enrollment_workflow_id"):
        op.create_index(op.f(f"ix_digital_human_profiles_{column}"), "digital_human_profiles", [column])

    op.create_table(
        "workflow_external_tasks",
        sa.Column("workflow_id", sa.String(length=36), nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("provider_task_id", sa.String(length=255), nullable=False, server_default=""),
        sa.Column("provider_status", sa.String(length=32), nullable=False),
        sa.Column("next_poll_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("poll_attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("max_poll_attempts", sa.Integer(), nullable=False, server_default="120"),
        sa.Column("consecutive_errors", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("lease_owner", sa.String(length=64), nullable=False, server_default=""),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("sanitized_request", sa.JSON(), nullable=False),
        sa.Column("last_response", sa.JSON(), nullable=False),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["workflow_id"], ["workflows.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("workflow_id"),
    )
    for column in ("provider", "provider_task_id", "next_poll_at"):
        op.create_index(op.f(f"ix_workflow_external_tasks_{column}"), "workflow_external_tasks", [column])


def downgrade() -> None:
    op.drop_table("workflow_external_tasks")
    op.drop_table("digital_human_profiles")
