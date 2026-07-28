from langchain_core.documents import Document
from data.src.models.GenerationResponse import GenerationResponse

def validate_context(query: str, documents: list[Document]) -> GenerationResponse | None:
    response = _validate_empty_context(documents)
    if response:
        return response

    response = _validate_relevance(query, documents)
    if response:
        return response

    return None

def _validate_empty_context(documents: list[Document]) -> GenerationResponse | None:
    if not documents:
        return GenerationResponse(
            success=False,
            reason="NO_CONTEXT",
            message="I couldn't find relevant information in the indexed documents."
        )
    return None

def _validate_relevance(query: str, documents: list[Document]) -> GenerationResponse | None:
    #Helper LLM (future)
    return None