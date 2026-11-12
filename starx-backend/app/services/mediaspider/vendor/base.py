from abc import ABC, abstractmethod


class AbstractCrawler(ABC):
    @abstractmethod
    async def start(self): ...


class AbstractStore(ABC):
    @abstractmethod
    async def store_content(self, item): ...

    @abstractmethod
    async def store_comment(self, item): ...

    @abstractmethod
    async def store_creator(self, item): ...


class AbstractApiClient: pass
class AbstractLogin: pass
