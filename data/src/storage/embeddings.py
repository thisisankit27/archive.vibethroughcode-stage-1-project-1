import time

from langchain_core.documents import Document
from langchain_ollama import OllamaEmbeddings

from data.src.config import EMBEDDING_BATCH_SIZE, EMBEDDING_MODEL, OLLAMA_BASE_URL
from data.src.resilience import call_with_retry


class EmbeddingService:

    _model = OllamaEmbeddings(
        model=EMBEDDING_MODEL,
        base_url=OLLAMA_BASE_URL,
    )

    # Changing the embedding model invalidates the whole index - stored vectors and query
    # vectors must come from the same model, or similarity search compares noise.
    _BATCH_SIZE = EMBEDDING_BATCH_SIZE

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

            # Retried per BATCH, not per document set. Embedding a batch is side-effect free -
            # nothing is written until VectorStore.store() runs later - so a repeat is safe.
            #
            # Contrast VectorStore.store() itself, which is NOT wrapped: it does index.add()
            # then documents.extend() then save(), so retrying it after a failed save would
            # put every chunk in the index twice.
            vectors.extend(
                call_with_retry(
                    "embedding.embed_documents",
                    "ollama",
                    lambda batch=batch: cls._model.embed_documents(batch),
                )
            )

        elapsed = time.perf_counter() - start

        dimension = len(vectors[0]) if vectors else 0

        return vectors, dimension, elapsed
    
    @classmethod
    def generate_query_embedding(
        cls,
        query: str,
    ) -> list[float]:

        return call_with_retry(
            "embedding.embed_query",
            "ollama",
            lambda: cls._model.embed_query(query),
        )