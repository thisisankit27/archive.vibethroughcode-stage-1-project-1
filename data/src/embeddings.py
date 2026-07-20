import time

from langchain_core.documents import Document
from langchain_ollama import OllamaEmbeddings


class EmbeddingService:

    _model = OllamaEmbeddings(
        model="embeddinggemma:latest"
    )

    _BATCH_SIZE = 100

    @classmethod
    def generate_embeddings(
        cls,
        chunks: list[Document],
    ) -> tuple[list[list[float]], int, float]:

        texts = [
            chunk.page_content
            for chunk in chunks
        ]

        vectors: list[list[float]] = []

        start = time.perf_counter()

        for i in range(0, len(texts), cls._BATCH_SIZE):

            batch = texts[i:i + cls._BATCH_SIZE]

            vectors.extend(
                cls._model.embed_documents(batch)
            )

        elapsed = time.perf_counter() - start

        dimension = len(vectors[0]) if vectors else 0

        return vectors, dimension, elapsed