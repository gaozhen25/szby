"""创建服务端发布尝试表并固定创作与流程任务的一对一绑定。"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "20260716_000022"
down_revision: str | None = "20260716_000021"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _json_default(value: str, dialect_name: str) -> sa.TextClause:
    suffix = "::json" if dialect_name == "postgresql" else ""
    return sa.text(f"'{value}'{suffix}")


def _write_legacy_publish_projection(
    bind: sa.Connection,
    content_creations: sa.Table,
    *,
    creation_id: str,
    latest_state: dict[str, object],
    history: list[dict[str, object]],
) -> None:
    existing_state = bind.execute(
        sa.select(content_creations.c.creation_state).where(
            content_creations.c.id == creation_id
        )
    ).scalar_one_or_none()
    creation_state = dict(existing_state) if isinstance(existing_state, dict) else {}
    creation_state["publish"] = latest_state
    creation_state["publishHistory"] = history[-50:]
    bind.execute(
        sa.update(content_creations)
        .where(content_creations.c.id == creation_id)
        .values(creation_state=creation_state)
    )


def _materialize_legacy_publish_projections(bind: sa.Connection) -> None:
    metadata = sa.MetaData()
    attempts = sa.Table(
        "creation_publish_attempts",
        metadata,
        autoload_with=bind,
    )
    content_creations = sa.Table(
        "content_creations",
        metadata,
        autoload_with=bind,
    )
    rows = bind.execute(
        sa.select(
            attempts.c.creation_id,
            attempts.c.state,
            attempts.c.history,
        ).order_by(attempts.c.creation_id, attempts.c.attempt)
    ).mappings()

    current_creation_id: str | None = None
    latest_state: dict[str, object] = {}
    history: list[dict[str, object]] = []
    for row in rows:
        creation_id = str(row["creation_id"])
        if current_creation_id is not None and creation_id != current_creation_id:
            _write_legacy_publish_projection(
                bind,
                content_creations,
                creation_id=current_creation_id,
                latest_state=latest_state,
                history=history,
            )
            history = []
        current_creation_id = creation_id
        latest_state = dict(row["state"]) if isinstance(row["state"], dict) else {}
        attempt_history = row["history"]
        if isinstance(attempt_history, list):
            history.extend(
                dict(event) for event in attempt_history if isinstance(event, dict)
            )
            history = history[-50:]

    if current_creation_id is not None:
        _write_legacy_publish_projection(
            bind,
            content_creations,
            creation_id=current_creation_id,
            latest_state=latest_state,
            history=history,
        )


def upgrade() -> None:
    bind = op.get_bind()
    dialect_name = bind.dialect.name
    tables = set(sa.inspect(bind).get_table_names())

    if "creation_publish_attempts" not in tables:
        op.create_table(
            "creation_publish_attempts",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column(
                "account_id",
                sa.String(36),
                sa.ForeignKey("accounts.id"),
                nullable=False,
            ),
            sa.Column(
                "user_id",
                sa.String(36),
                sa.ForeignKey("users.id"),
                nullable=False,
            ),
            sa.Column(
                "creation_id",
                sa.String(36),
                sa.ForeignKey("content_creations.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("attempt", sa.Integer(), nullable=False),
            sa.Column("external_id", sa.String(255), nullable=False),
            sa.Column("platform", sa.String(32), nullable=False),
            sa.Column("status", sa.String(32), nullable=False),
            sa.Column(
                "state",
                sa.JSON(),
                nullable=False,
                server_default=_json_default("{}", dialect_name),
            ),
            sa.Column(
                "history",
                sa.JSON(),
                nullable=False,
                server_default=_json_default("[]", dialect_name),
            ),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
            sa.UniqueConstraint(
                "creation_id",
                "attempt",
                name="uq_creation_publish_attempt_number",
            ),
            sa.UniqueConstraint(
                "external_id",
                name="uq_creation_publish_attempt_external_id",
            ),
        )
        op.create_index(
            "ix_creation_publish_attempts_account_id",
            "creation_publish_attempts",
            ["account_id"],
        )
        op.create_index(
            "ix_creation_publish_attempts_user_id",
            "creation_publish_attempts",
            ["user_id"],
        )
        op.create_index(
            "ix_creation_publish_attempts_creation_id",
            "creation_publish_attempts",
            ["creation_id"],
        )

    # 旧数据可能把其他账号的创作或同一创作重复绑定到任务。保留原门禁会选中的
    # 最大任务 ID，其余任务只解除创作绑定，不删除任务内容。
    bind.execute(
        sa.text(
            """
            UPDATE tasks
               SET creation_id = NULL
             WHERE creation_id IS NOT NULL
               AND NOT EXISTS (
                   SELECT 1
                     FROM content_creations
                    WHERE content_creations.id = tasks.creation_id
                      AND content_creations.account_id = tasks.account_id
               )
            """
        )
    )
    bind.execute(
        sa.text(
            """
            UPDATE tasks
               SET creation_id = NULL
             WHERE creation_id IS NOT NULL
               AND id NOT IN (
                   SELECT MAX(id)
                     FROM tasks
                    WHERE creation_id IS NOT NULL
                    GROUP BY creation_id
               )
            """
        )
    )

    unique_constraints = {
        constraint["name"]
        for constraint in sa.inspect(bind).get_unique_constraints("tasks")
    }
    if "uq_tasks_creation_id" not in unique_constraints:
        with op.batch_alter_table("tasks") as batch_op:
            batch_op.create_unique_constraint("uq_tasks_creation_id", ["creation_id"])


def downgrade() -> None:
    bind = op.get_bind()
    tables = set(sa.inspect(bind).get_table_names())
    if "creation_publish_attempts" in tables:
        _materialize_legacy_publish_projections(bind)
        op.drop_table("creation_publish_attempts")

    unique_constraints = {
        constraint["name"]
        for constraint in sa.inspect(bind).get_unique_constraints("tasks")
    }
    if "uq_tasks_creation_id" in unique_constraints:
        with op.batch_alter_table("tasks") as batch_op:
            batch_op.drop_constraint("uq_tasks_creation_id", type_="unique")
