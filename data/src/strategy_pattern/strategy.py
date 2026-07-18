# Abstract Strategy
from abc import ABC, abstractmethod
from langchain_core.documents import Document

class Strategy(ABC):

    @abstractmethod
    def chunk(self, document) -> list[Document]:
        pass