from abc import ABC, abstractmethod

from query.models.query import RetrievalQuery
from query.models.result import RetrievalResult


class BaseRetriever(ABC):

    @abstractmethod
    async def retrieve(self, query: RetrievalQuery) -> RetrievalResult: ...

    @abstractmethod
    def health_check(self) -> bool: ...
