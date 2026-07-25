from abc import ABC, abstractmethod

from langchain_core.documents import Document


class SparseIndexer(ABC):
    """
    Contract for building and persisting a sparse index.
    """

    @abstractmethod
    def index(self, chunks: list[Document]) -> None:
        """
        Builds a sparse index from document chunks.
        """
        pass

    @abstractmethod
    def save(self) -> None:
        """
        Persists the constructed sparse index.
        """
        pass

    @abstractmethod
    def load(self) -> None:
        """
        Loads a previously persisted sparse index.
        """
        pass

    @abstractmethod
    def search(self, query: str, top_k: int) -> list[Document]:
        pass