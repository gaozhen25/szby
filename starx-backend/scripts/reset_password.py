"""重置 StarX 用户密码并输出新登录凭据。

用法：
    conda run -n starx python -m scripts.reset_password \
        --email user@example.com

默认生成高强度随机密码；也可以通过 ``--password`` 指定新密码。
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

from sqlalchemy.orm import Session

# 兼容 ``python scripts/reset_password.py`` 和 ``python -m scripts.reset_password``。
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.db.init_db import create_app_engine
from app.db.manage_users import change_password
from scripts.create_user import generate_password


@dataclass(frozen=True)
class ResetCredentials:
    account: str
    password: str
    user_id: str


def reset_password(
    session: Session,
    *,
    email: str,
    password: str | None = None,
) -> ResetCredentials:
    """重置用户密码，并返回仅供本次展示的新登录凭据。"""
    new_password = password or generate_password()
    user = change_password(session, email=email, password=new_password)
    return ResetCredentials(
        account=user.email,
        password=new_password,
        user_id=user.id,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="重置 StarX 用户密码并返回新登录凭据")
    parser.add_argument("--email", required=True, help="需要重置密码的登录邮箱")
    parser.add_argument("--password", help="新密码，省略时自动生成安全随机密码")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    engine = create_app_engine()
    with Session(engine) as session:
        try:
            credentials = reset_password(
                session,
                email=args.email,
                password=args.password,
            )
        except ValueError as exc:
            messages = {
                "user_not_found": "用户不存在",
                "password_too_short": "密码长度不能少于 6 位",
            }
            print(messages.get(str(exc), str(exc)), file=sys.stderr)
            return 1

    print(json.dumps(asdict(credentials), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
