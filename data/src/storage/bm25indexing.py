import pickle
from pathlib import Path

from langchain_core.documents import Document
from rank_bm25 import BM25Okapi

from data.src.storage.sparse_indexing import SparseIndexer

INDEX_PATH = Path("./storage/bm25.index")


class BM25Indexer(SparseIndexer):

    def __init__(self):
        self._model = None
        self._documents: list[Document] = []

        INDEX_PATH.parent.mkdir(parents=True, exist_ok=True)

    def index(self, chunks: list[Document]) -> dict:
        """
        Builds (or updates) the BM25 index from document chunks
        and persists it.
        """

        # Load existing index if available
        self.load()

        # Append newly uploaded chunks
        self._documents.extend(chunks)

        tokenized_texts = [
            document.page_content.lower().split()
            for document in self._documents
        ]

        self._model = BM25Okapi(tokenized_texts)

        self.save()

        return {
            "indexed_documents": len(self._documents),
            "vocabulary_size": len(self._model.idf),
            "tokenized_documents": len(tokenized_texts),
        }

    def save(self) -> None:
        """
        Persists the BM25 model and original documents.
        """

        state = {
            "model": self._model,
            "documents": self._documents,
        }

        with INDEX_PATH.open("wb") as file:
            pickle.dump(state, file)

    def load(self) -> None:
        """
        Loads a previously persisted BM25 index.
        """

        if not INDEX_PATH.exists():
            return

        with INDEX_PATH.open("rb") as file:
            state = pickle.load(file)

        self._model = state["model"]
        self._documents = state["documents"]

    def search(self, query: str, top_k: int) -> list[Document]:
        self.load()
        if self._model is None:
            # raise ValueError("Index is not loaded or initialized.")
            return []
        tokenized_query = query.lower().split()
        return self._model.get_top_n(tokenized_query, self._documents, n=top_k)

        