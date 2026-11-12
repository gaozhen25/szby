"""创建 StarX 用户并输出初始登录凭据。

用法：
    conda run -n starx python -m scripts.create_user \
        --email user@example.com --nickname "用户昵称"

默认生成高强度随机密码；也可以通过 ``--password`` 指定初始密码。
"""

from __future__ import annotations

import argparse
import json
import secrets
import string
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

from sqlalchemy.orm import Session

# 兼容 ``python scripts/create_user.py`` 和 ``python -m scripts.create_user``。
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.db.init_db import create_app_engine
from app.db.manage_users import add_user


DEFAULT_PASSWORD_LENGTH = 16
PASSWORD_SYMBOLS = "-_@#"


@dataclass(frozen=True)
class CreatedCredentials:
    account: str
    password: str
    user_id: str
    nickname: str


def generate_password(length: int = DEFAULT_PASSWORD_LENGTH) -> str:
    """生成至少包含大小写字母、数字和符号的密码。"""
    if length < 12:
        raise ValueError("password_length_too_short")

    character_groups = (
        string.ascii_lowercase,
        string.ascii_uppercase,
        string.digits,
        PASSWORD_SYMBOLS,
    )
    characters = [secrets.choice(group) for group in character_groups]
    alphabet = "".join(character_groups)
    characters.extend(secrets.choice(alphabet) for _ in range(length - len(characters)))
    secrets.SystemRandom().shuffle(characters)
    return "".join(characters)


def create_user(
    session: Session,
    *,
    email: str,
    nickname: str = "",
    password: str | None = None,
    user_id: str | None = None,
) -> CreatedCredentials:
    """创建用户，并返回仅供本次展示的初始登录凭据。"""
    initial_password = password or generate_password()
    user = add_user(
        session,
        email=email,
        password=initial_password,
        nickname=nickname,
        user_id=user_id,
    )
    return CreatedCredentials(
        account=user.email,
        password=initial_password,
        user_id=user.id,
        nickname=user.nickname,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="创建 StarX 用户并返回账号和初始密码")
    parser.add_argument("--email", required=True, help="登录邮箱（即登录账号）")
    parser.add_argument("--nickname", default="", help="用户昵称，默认使用邮箱前缀")
    parser.add_argument("--password", help="初始密码，省略时自动生成安全随机密码")
    parser.add_argument("--id", dest="user_id", help="自定义用户 ID，通常无需指定")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    engine = create_app_engine()
    with Session(engine) as session:
        try:
            credentials = create_user(
                session,
                email=args.email,
                nickname=args.nickname,
                password=args.password,
                user_id=args.user_id,
            )
        except ValueError as exc:
            messages = {
                "user_exists": "用户已存在",
                "password_too_short": "密码长度不能少于 6 位",
            }
            print(messages.get(str(exc), str(exc)), file=sys.stderr)
            return 1

    print(json.dumps(asdict(credentials), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
