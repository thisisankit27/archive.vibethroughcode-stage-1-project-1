import pickle
from pathlib import Path

import faiss
import numpy as np
from langchain_core.documents import Document

from data.src.embeddings import EmbeddingService


INDEX_PATH = Path("./storage/my_index.index")
DOCUMENTS_PATH = Path("./storage/documents.pkl")


class VectorStore:

    def __init__(self):
        self._index = None
        self._documents: list[Document] = []

        INDEX_PATH.parent.mkdir(exist_ok=True)

        if INDEX_PATH.is_file():
            self._index = faiss.read_index(str(INDEX_PATH))

        if DOCUMENTS_PATH.is_file():
            with open(DOCUMENTS_PATH, "rb") as file:
                self._documents = pickle.load(file)

    def store(
        self,
        documents: list[Document],
        embeddings: list[list[float]],
    ) -> None:

        if not embeddings:
            return

        if self._index is None:
            dimension = len(embeddings[0])
            self._index = faiss.IndexFlatL2(dimension)

        faiss_ready_array = np.ascontiguousarray(
            embeddings,
            dtype=np.float32,
        )

        self._index.add(faiss_ready_array)

        self._documents.extend(documents)

        self.save()

    def save(self) -> None:

        if self._index is not None:
            faiss.write_index(self._index, str(INDEX_PATH))

        with open(DOCUMENTS_PATH, "wb") as file:
            pickle.dump(self._documents, file)

    def search(
        self,
        query: str,
        k: int = 2,
    ) -> list[Document]:

        if self._index is None:
            return []

        query_embedding = EmbeddingService.generate_query_embedding(query)

        query_embedding = np.ascontiguousarray(
            [query_embedding],
            dtype=np.float32,
        )

        k = min(k, len(self._documents))

        distances, indices = self._index.search(
            query_embedding,
            k,
        )

        matched_documents: list[Document] = []

        for distance, index in zip(distances[0], indices[0]):
            if index != -1:
                matched_documents.append(self._documents[index])

        return matched_documents