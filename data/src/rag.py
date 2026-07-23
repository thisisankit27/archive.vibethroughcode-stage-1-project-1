from data.src.embeddings import EmbeddingService
from data.src.vector_store import VectorStore
from data.src.generation_service import GenerationService

TOP_K = 3

def ask(query):
    query_embedding = EmbeddingService.generate_query_embedding(query)
    _vector_store = VectorStore()
    matched_docs = _vector_store.search(query_embedding, TOP_K)

    return GenerationService.generate_answer(query, matched_docs)