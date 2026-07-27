from langchain_core.documents import Document

from data.src.storage.embeddings import EmbeddingService
from data.src.storage.vector_store import VectorStore

_vector_store = VectorStore()

class DenseRetriever:

    @classmethod
    def retrieve(cls, query: str, top_k: int) -> list[Document]:
        query_embedding = EmbeddingService.generate_query_embedding(query)
        matched_dense_vector_docs = _vector_store.search(query_embedding, top_k)

        return matched_dense_vector_docs