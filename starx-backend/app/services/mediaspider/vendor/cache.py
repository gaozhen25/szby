import time


class ExpiringLocalCache:
    def __init__(self, *args, **kwargs):
        self._values = {}

    def get(self, key):
        value, expires = self._values.get(key, (None, 0))
        if expires < time.time():
            self._values.pop(key, None)
            return None
        return value

    def set(self, key, value, expire_time):
        self._values[key] = (value, time.time() + expire_time)


class CacheFactory:
    @staticmethod
    def create_cache(cache_type, *args, **kwargs):
        if cache_type != "memory":
            raise ValueError("内嵌运行时只支持内存缓存")
        return ExpiringLocalCache(*args, **kwargs)
