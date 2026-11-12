from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy.exc import IntegrityError


MIGRATION_PATH = (
    Path(__file__).parents[1]
    / "alembic"
    / "versions"
    / "20260716_000022_creation_publish_attempts.py"
)


def _load_migration():
    spec = spec_from_file_location("creation_publish_attempts_migration", MIGRATION_PATH)
    assert spec is not None and spec.loader is not None
    migration = module_from_spec(spec)
    spec.loader.exec_module(migration)
    return migration


def test_creation_publish_attempt_migration_exists():
    assert MIGRATION_PATH.exists()


def test_creation_publish_attempt_migration_metadata():
    migration = _load_migration()
    assert migration.revision == "20260716_000022"
    assert migration.down_revision == "20260716_000021"


def test_creation_publish_attempt_migration_cleans_task_bindings_and_adds_constraints(tmp_path):
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'migration.db'}")
    metadata = sa.MetaData()
    sa.Table("users", metadata, sa.Column("id", sa.String(36), primary_key=True))
    sa.Table("accounts", metadata, sa.Column("id", sa.String(36), primary_key=True))
    content_creations = sa.Table(
        "content_creations",
        metadata,
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("account_id", sa.String(36), nullable=False),
        sa.Column("user_id", sa.String(36), nullable=False),
        sa.Column(
            "creation_state",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'{}'"),
        ),
    )
    tasks = sa.Table(
        "tasks",
        metadata,
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("account_id", sa.String(36), nullable=False),
        sa.Column("creation_id", sa.String(36), nullable=True),
        sa.Column(
            "status",
            sa.String(32),
            nullable=False,
            server_default="draft",
        ),
    )
    metadata.create_all(engine)

    with engine.begin() as connection:
        connection.execute(sa.text("INSERT INTO users (id) VALUES ('user-1')"))
        connection.execute(sa.text("INSERT INTO accounts (id) VALUES ('account-1'), ('account-2')"))
        connection.execute(
            content_creations.insert(),
            [
                {"id": "creation-1", "account_id": "account-1", "user_id": "user-1"},
                {"id": "creation-2", "account_id": "account-1", "user_id": "user-1"},
                {"id": "creation-3", "account_id": "account-1", "user_id": "user-1"},
            ],
        )
        connection.execute(
            tasks.insert(),
            [
                {
                    "id": "task-1",
                    "account_id": "account-1",
                    "creation_id": "creation-1",
                },
                {
                    "id": "task-2",
                    "account_id": "account-1",
                    "creation_id": "creation-1",
                },
                {
                    "id": "task-3",
                    "account_id": "account-2",
                    "creation_id": "creation-1",
                },
                {
                    "id": "task-4",
                    "account_id": "account-1",
                    "creation_id": "creation-2",
                },
                {
                    "id": "task-5",
                    "account_id": "account-1",
                    "creation_id": "creation-3",
                },
                {
                    "id": "task-6",
                    "account_id": "account-1",
                    "creation_id": None,
                },
            ],
        )

        migration = _load_migration()
        migration.op = Operations(MigrationContext.configure(connection))
        migration.upgrade()

    inspector = sa.inspect(engine)
    assert "creation_publish_attempts" in inspector.get_table_names()
    assert {constraint["name"] for constraint in inspector.get_unique_constraints("tasks")} == {
        "uq_tasks_creation_id"
    }
    with engine.connect() as connection:
        bindings = dict(connection.execute(sa.select(tasks.c.id, tasks.c.creation_id)).all())
    assert bindings == {
        "task-1": None,
        "task-2": "creation-1",
        "task-3": None,
        "task-4": "creation-2",
        "task-5": "creation-3",
        "task-6": None,
    }

    with pytest.raises(IntegrityError):
        with engine.begin() as connection:
            connection.execute(
                tasks.insert().values(
                    id="task-7",
                    account_id="account-1",
                    creation_id="creation-1",
                )
            )

    with engine.begin() as connection:
        migration.op = Operations(MigrationContext.configure(connection))
        migration.downgrade()

    inspector = sa.inspect(engine)
    assert "creation_publish_attempts" not in inspector.get_table_names()
    assert inspector.get_unique_constraints("tasks") == []
    engine.dispose()


def test_downgrade_materializes_latest_publish_projection_before_dropping_attempts(
    tmp_path,
):
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'roundtrip.db'}")
    metadata = sa.MetaData()
    users = sa.Table("users", metadata, sa.Column("id", sa.String(36), primary_key=True))
    accounts = sa.Table(
        "accounts",
        metadata,
        sa.Column("id", sa.String(36), primary_key=True),
    )
    content_creations = sa.Table(
        "content_creations",
        metadata,
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("account_id", sa.String(36), nullable=False),
        sa.Column("user_id", sa.String(36), nullable=False),
        sa.Column("creation_state", sa.JSON(), nullable=False),
    )
    sa.Table(
        "tasks",
        metadata,
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("account_id", sa.String(36), nullable=False),
        sa.Column("creation_id", sa.String(36), nullable=True),
        sa.Column(
            "status",
            sa.String(32),
            nullable=False,
            server_default="draft",
        ),
    )
    metadata.create_all(engine)

    first_state = {
        "externalId": "publish-1",
        "status": "failed",
        "attempt": 1,
    }
    latest_state = {
        "externalId": "publish-2",
        "status": "queued",
        "attempt": 2,
    }
    first_history = [
        {"sequence": sequence, "attempt": 1}
        for sequence in range(1, 31)
    ]
    latest_history = [
        {"sequence": sequence, "attempt": 2}
        for sequence in range(31, 61)
    ]

    with engine.begin() as connection:
        connection.execute(users.insert().values(id="user-1"))
        connection.execute(accounts.insert().values(id="account-1"))
        connection.execute(
            content_creations.insert(),
            [
                {
                    "id": "creation-1",
                    "account_id": "account-1",
                    "user_id": "user-1",
                    "creation_state": {
                        "version": 7,
                        "selectedVariants": {"slot-1": "variant-1"},
                        "publish": dict(first_state),
                        "publishHistory": [{"sequence": 0, "attempt": 1}],
                    },
                },
                {
                    "id": "creation-2",
                    "account_id": "account-1",
                    "user_id": "user-1",
                    "creation_state": {"version": 3, "mode": "secondary"},
                },
            ],
        )

        migration = _load_migration()
        migration.op = Operations(MigrationContext.configure(connection))
        migration.upgrade()
        attempts = sa.Table(
            "creation_publish_attempts",
            sa.MetaData(),
            autoload_with=connection,
        )
        connection.execute(
            attempts.insert(),
            [
                {
                    "account_id": "account-1",
                    "user_id": "user-1",
                    "creation_id": "creation-1",
                    "attempt": 2,
                    "external_id": "publish-2",
                    "platform": "douyin",
                    "status": "queued",
                    "state": latest_state,
                    "history": latest_history,
                },
                {
                    "account_id": "account-1",
                    "user_id": "user-1",
                    "creation_id": "creation-2",
                    "attempt": 1,
                    "external_id": "publish-secondary",
                    "platform": "douyin",
                    "status": "succeeded",
                    "state": {
                        "externalId": "publish-secondary",
                        "status": "succeeded",
                        "attempt": 1,
                    },
                    "history": [{"sequence": 1, "attempt": 1}],
                },
                {
                    "account_id": "account-1",
                    "user_id": "user-1",
                    "creation_id": "creation-1",
                    "attempt": 1,
                    "external_id": "publish-1",
                    "platform": "douyin",
                    "status": "failed",
                    "state": first_state,
                    "history": first_history,
                },
            ],
        )

        migration.downgrade()

    assert "creation_publish_attempts" not in sa.inspect(engine).get_table_names()
    with engine.connect() as connection:
        states = dict(
            connection.execute(
                sa.select(content_creations.c.id, content_creations.c.creation_state)
            ).all()
        )

    assert states["creation-1"]["version"] == 7
    assert states["creation-1"]["selectedVariants"] == {"slot-1": "variant-1"}
    assert states["creation-1"]["publish"] == latest_state
    assert [
        event["sequence"] for event in states["creation-1"]["publishHistory"]
    ] == list(range(11, 61))
    assert states["creation-2"] == {
        "version": 3,
        "mode": "secondary",
        "publish": {
            "externalId": "publish-secondary",
            "status": "succeeded",
            "attempt": 1,
        },
        "publishHistory": [{"sequence": 1, "attempt": 1}],
    }
    engine.dispose()
