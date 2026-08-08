from langchain_core.documents import Document
from data.src.models.GenerationResponse import GenerationResponse
from data.src.observability import get_logger, log_event

_logger = get_logger("guardrails.context")

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
        log_event(_logger, "guardrail.rejected", reason="NO_CONTEXT")
        return GenerationResponse(
            success=False,
            reason="NO_CONTEXT",
            message="I couldn't find relevant information in the indexed documents."
        )
    return None

def _validate_relevance(query: str, documents: list[Document]) -> GenerationResponse | None:
    #Helper LLM (future)
    return None