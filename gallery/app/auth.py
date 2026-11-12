"""Admin session cookie. The secret is the library API key."""

from __future__ import annotations

import hashlib
import hmac
import time

COOKIE = "gallery_session"
MAX_AGE = 7 * 24 * 3600


def issue_token(secret: str, now: int | None = None) -> str:
    exp = (now if now is not None else int(time.time())) + MAX_AGE
    msg = str(exp).encode()
    sig = hmac.new(secret.encode(), msg, hashlib.sha256).hexdigest()
    return f"{exp}.{sig}"


def token_ok(token: str, secret: str, now: int | None = None) -> bool:
    if not token or "." not in token or not secret:
        return False
    exp, sig = token.split(".", 1)
    if not exp.isdigit():
        return False
    if int(exp) < (now if now is not None else int(time.time())):
        return False
    expected = hmac.new(secret.encode(), exp.encode(), hashlib.sha256).hexdigest()
    if len(sig) != len(expected):
        return False
    return hmac.compare_digest(sig, expected)
