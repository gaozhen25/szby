from redis import Redis
from urllib.parse import quote

from app.core.config import settings


def _normalize_redis_url(url: str) -> str:
    marker = "://:"
    if "#" not in url or marker not in url or "@" not in url:
        return url
    scheme, remainder = url.split(marker, 1)
    password, address = remainder.rsplit("@", 1)
    return f"{scheme}{marker}{quote(password, safe='')}@{address}"


def get_redis() -> Redis:
    return Redis.from_url(_normalize_redis_url(settings.redis_url), decode_responses=True)
