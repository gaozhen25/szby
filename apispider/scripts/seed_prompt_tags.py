"""
Seed built-in prompt tags and categories into the database.

Usage:
    cd starx-backend && python -m scripts.seed_prompt_tags
    # or directly:
    python scripts/seed_prompt_tags.py

This script is idempotent — it only inserts categories/tags that don't already exist
for each account.
"""

import sys
from pathlib import Path

# Ensure the starx-backend root is on sys.path so `app.*` imports work
# regardless of how this script is invoked.
_project_root = Path(__file__).resolve().parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from datetime import UTC, datetime

from app.core.database import create_app_engine
from app.db.base import Base
from app.db.models import (
    AccountRecord,
    GenerationPromptTagCategoryRecord,
    GenerationPromptTagRecord,
)
from app.services.prompt_tags import prompt_tag_categories
from sqlalchemy.orm import Session


def _stable_uuid(prefix: str, *parts: str) -> str:
    """Generate a deterministic ID from prefix + parts (avoid duplicates on re-run)."""
    import hashlib
    digest = hashlib.md5(":".join(parts).encode()).hexdigest()
    return f"{prefix}_{digest}"


def _cleanup_stale(session: Session) -> int:
    """Delete DB tags/categories that are NOT in the current built-in prompt_tag_categories."""
    from sqlalchemy import delete as _delete  # noqa: F811

    valid_cat_labels = {cat["label"] for cat in prompt_tag_categories}
    valid_tag_labels = set()
    for cat_def in prompt_tag_categories:
        for tag_def in cat_def["tags"]:
            valid_tag_labels.add(tag_def["label"])

    # Delete stale tags (labels not in built-in)
    stale_tags = session.query(GenerationPromptTagRecord).filter(
        GenerationPromptTagRecord.label.notin_(valid_tag_labels)
    ).delete(synchronize_session=False)

    # Delete stale categories (labels not in built-in)
    stale_cats = session.query(GenerationPromptTagCategoryRecord).filter(
        GenerationPromptTagCategoryRecord.label.notin_(valid_cat_labels)
    ).delete(synchronize_session=False)

    return stale_cats + stale_tags


def seed_prompt_tags(session: Session) -> dict[str, int]:
    """Seed built-in prompt tag categories and tags into DB.

    Returns stats: {'categories': N, 'tags': N}
    """
    stats = {"categories": 0, "tags": 0}

    # Get all active accounts (categories/tags are per-account)
    accounts = session.query(AccountRecord).filter(AccountRecord.status == "active").all()
    if not accounts:
        print("No active accounts found — skipping seed.")
        return stats

    now = datetime.now(UTC)

    # First clean up stale entries
    stale = _cleanup_stale(session)
    if stale:
        print(f"Cleaned up {stale} stale tags/categories")

    for account in accounts:
        for cat_idx, cat_def in enumerate(prompt_tag_categories):
            cat_label = cat_def["label"]
            cat_id = _stable_uuid("ptc", account.id, cat_label)

            existing_cat = session.query(GenerationPromptTagCategoryRecord).filter(
                GenerationPromptTagCategoryRecord.id == cat_id,
            ).first()

            if existing_cat is None:
                session.add(GenerationPromptTagCategoryRecord(
                    id=cat_id,
                    account_id=account.id,
                    user_id=account.user_id,
                    label=cat_label,
                    sort_order=cat_idx,
                    created_at=now,
                    updated_at=now,
                ))
                stats["categories"] += 1

            for tag_idx, tag_def in enumerate(cat_def["tags"]):
                tag_label = tag_def["label"]
                tag_id = _stable_uuid("pt", account.id, tag_label)

                existing_tag = session.query(GenerationPromptTagRecord).filter(
                    GenerationPromptTagRecord.id == tag_id,
                ).first()

                if existing_tag is None:
                    session.add(GenerationPromptTagRecord(
                        id=tag_id,
                        category_id=cat_id,
                        account_id=account.id,
                        user_id=account.user_id,
                        label=tag_label,
                        prompt=tag_def["prompt"],
                        sort_order=tag_idx,
                        created_at=now,
                        updated_at=now,
                    ))
                    stats["tags"] += 1

        session.flush()

    session.commit()
    return stats


def main() -> None:
    engine = create_app_engine()
    # Ensure tables exist (in case migrations haven't been run individually)
    Base.metadata.create_all(bind=engine)

    with Session(engine) as session:
        stats = seed_prompt_tags(session)
        print(f"Seeded {stats['categories']} categories, {stats['tags']} tags")


if __name__ == "__main__":
    main()
