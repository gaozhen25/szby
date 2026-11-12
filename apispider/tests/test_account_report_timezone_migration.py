from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from types import SimpleNamespace

import sqlalchemy as sa


MIGRATION_PATH = Path(__file__).parents[1] / "alembic" / "versions" / "20260714_000020_account_report_generated_at_timezone.py"
spec = spec_from_file_location("account_report_timezone_migration", MIGRATION_PATH)
assert spec is not None and spec.loader is not None
migration = module_from_spec(spec)
spec.loader.exec_module(migration)


def test_account_report_timezone_migration_metadata():
    assert migration.revision == "20260714_000020"
    assert migration.down_revision == "20260714_000019"


def test_upgrade_converts_naive_generated_at_to_utc_timestamptz(monkeypatch):
    calls: list[tuple[tuple[object, ...], dict[str, object]]] = []
    bind = SimpleNamespace(dialect=SimpleNamespace(name="postgresql"))
    inspector = SimpleNamespace(
        get_columns=lambda table_name: [
            {"name": "generated_at", "type": sa.DateTime(timezone=False)}
        ]
    )
    monkeypatch.setattr(migration.op, "get_bind", lambda: bind)
    monkeypatch.setattr(migration, "inspect", lambda _bind: inspector)
    monkeypatch.setattr(migration.op, "alter_column", lambda *args, **kwargs: calls.append((args, kwargs)))

    migration.upgrade()

    assert len(calls) == 1
    args, kwargs = calls[0]
    assert args == ("reports", "generated_at")
    assert isinstance(kwargs["existing_type"], sa.DateTime)
    assert kwargs["existing_type"].timezone is False
    assert isinstance(kwargs["type_"], sa.DateTime)
    assert kwargs["type_"].timezone is True
    assert kwargs["existing_nullable"] is True
    assert kwargs["postgresql_using"] == "generated_at AT TIME ZONE 'UTC'"


def test_upgrade_is_idempotent_when_generated_at_is_already_timestamptz(monkeypatch):
    calls: list[object] = []
    bind = SimpleNamespace(dialect=SimpleNamespace(name="postgresql"))
    inspector = SimpleNamespace(
        get_columns=lambda table_name: [
            {"name": "generated_at", "type": sa.DateTime(timezone=True)}
        ]
    )
    monkeypatch.setattr(migration.op, "get_bind", lambda: bind)
    monkeypatch.setattr(migration, "inspect", lambda _bind: inspector)
    monkeypatch.setattr(migration.op, "alter_column", lambda *args, **kwargs: calls.append((args, kwargs)))

    migration.upgrade()

    assert calls == []
