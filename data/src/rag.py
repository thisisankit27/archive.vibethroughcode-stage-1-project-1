from data.src.generation_service import GenerationService
from data.src.retriever.retrieval_service import RetrievalService

TOP_K = 3

def ask(query):
    matched_docs = RetrievalService.retrieve(query,TOP_K)
    return GenerationService.generate_answer(query, matched_docs)