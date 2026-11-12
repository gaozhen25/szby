from __future__ import annotations

import argparse
from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.security import get_password_hash
from app.db.init_db import create_app_engine
from app.db.models import UserRecord


def _validate_password(password: str) -> None:
    if len(password) < 6:
        raise ValueError("password_too_short")


def add_user(
    session: Session,
    *,
    email: str,
    password: str,
    nickname: str,
    user_id: str | None = None,
) -> UserRecord:
    _validate_password(password)
    normalized_email = email.strip().lower()
    existing = session.scalar(select(UserRecord).where(UserRecord.email == normalized_email))
    if existing is not None:
        raise ValueError("user_exists")

    user = UserRecord(
        id=user_id or f"u_{uuid4().hex[:12]}",
        email=normalized_email,
        password_hash=get_password_hash(password),
        nickname=nickname.strip() or normalized_email.split("@", 1)[0],
        status="active",
    )
    session.add(user)
    session.commit()
    session.refresh(user)
    return user


def change_password(session: Session, *, email: str, password: str) -> UserRecord:
    _validate_password(password)
    normalized_email = email.strip().lower()
    user = session.scalar(select(UserRecord).where(UserRecord.email == normalized_email))
    if user is None:
        raise ValueError("user_not_found")

    user.password_hash = get_password_hash(password)
    user.updated_at = datetime.now(UTC)
    session.commit()
    session.refresh(user)
    return user


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Manage StarX toB accounts")
    subparsers = parser.add_subparsers(dest="command", required=True)

    add_parser = subparsers.add_parser("add", help="Add a new active toB account")
    add_parser.add_argument("--email", required=True)
    add_parser.add_argument("--password", required=True)
    add_parser.add_argument("--nickname", required=True)
    add_parser.add_argument("--id", dest="user_id")

    password_parser = subparsers.add_parser("change-password", help="Change a toB account password")
    password_parser.add_argument("--email", required=True)
    password_parser.add_argument("--password", required=True)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    engine = create_app_engine()
    with Session(engine) as session:
        try:
            if args.command == "add":
                user = add_user(
                    session,
                    email=args.email,
                    password=args.password,
                    nickname=args.nickname,
                    user_id=args.user_id,
                )
                print(f"created toB account {user.email} ({user.id})")
            elif args.command == "change-password":
                user = change_password(session, email=args.email, password=args.password)
                print(f"changed password for toB account {user.email} ({user.id})")
        except ValueError as exc:
            print(str(exc))
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
