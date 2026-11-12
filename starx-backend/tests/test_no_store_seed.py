from pathlib import Path


def test_store_and_seed_services_are_removed_from_runtime():
    root = Path(__file__).resolve().parents[1]

    assert not (root / "app" / "services" / "store.py").exists()
    assert not (root / "app" / "services" / "seed.py").exists()

    for path in (root / "app").rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        assert "app.services.store" not in text
        assert "app.services.seed" not in text
