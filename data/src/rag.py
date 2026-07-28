from data.src.generation_service import GenerationService
from data.src.models.GenerationResponse import GenerationResponse
from data.src.retriever.retrieval_service import RetrievalService
from data.src.guardrails.input_guardrails import validate_input
from data.src.guardrails.context_guardrails import validate_context
from data.src.guardrails.output_guardrails import validate_output

TOP_K = 3

def ask(query: str, filters: dict) -> GenerationResponse:
    # Input Guardrails
    guardrail_response = validate_input(query)
    if guardrail_response:
        return guardrail_response

    matched_docs = RetrievalService.retrieve(query,TOP_K, filters)
    # Context Validation Guardrails
    guardrail_response = validate_context(query, matched_docs)
    if guardrail_response:
        return guardrail_response

    generation_response = GenerationService.generate_answer(query, matched_docs)
    # Output Validation Guardrails
    guardrail_response = validate_output(generation_response)
    if guardrail_response:
        return guardrail_response

    return generation_response