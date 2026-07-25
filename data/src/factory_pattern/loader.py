from abc import ABC, abstractmethod
from langchain_core.documents import Document


class Loader(ABC):

    @abstractmethod
    def load(self) -> list[Document]:
        pass