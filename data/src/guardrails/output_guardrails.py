import re
from data.src.models.GenerationResponse import GenerationResponse
from langchain_core.documents import Document

def validate_output(generation_response: GenerationResponse) -> GenerationResponse | None:
    response = _check_empty_response(generation_response)
    if response:
        return response
    
    response = _validate_relevance(generation_response.answer, generation_response.documents)
    if response:
        return response
    
    response = _check_safety(generation_response.answer)
    if response:
        return response

    return None

def _check_empty_response(response: GenerationResponse) -> GenerationResponse | None:
    if not response.answer or not response.answer.strip():
        response.success = False
        response.reason="EMPTY_RESPONSE"
        response.message="The language model did not generate a valid response."
        return response

    return None

def _validate_relevance(response: str, documents: list[Document]) -> GenerationResponse | None:
    #Helper LLM (future)
    return None

def _check_safety(query: str) -> GenerationResponse | None:
    #Helper LLM (future)
    return None