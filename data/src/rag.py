from data.src.generation_service import GenerationService
from data.src.retriever.retrieval_service import RetrievalService

TOP_K = 3

def ask(query: str, filters: dict):
    matched_docs = RetrievalService.retrieve(query,TOP_K, filters)
    return GenerationService.generate_answer(query, matched_docs)