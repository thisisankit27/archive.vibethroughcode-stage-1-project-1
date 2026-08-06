import re
from data.src.models.GenerationResponse import GenerationResponse
from data.src.models.CitedSource import CitedSource

# Matches a citation marker such as [1] or [12], plus any spaces/tabs before it,
# so removing a marker does not leave a dangling space ("... k=60 ." )
_CITATION_PATTERN = re.compile(r"[ \t]*\[(\d+)\]")


def validate_output(generation_response: GenerationResponse) -> GenerationResponse | None:
    response = _check_empty_response(generation_response)
    if response:
        return response

    # Sanitizer, not a validator: repairs the answer in place, never rejects it.
    _strip_unverified_citations(generation_response)

    response = _validate_relevance(generation_response.answer, generation_response.sources)
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

# Drops citation markers the model invented, keeping the answer itself intact.
# A wrong attribution is worse than a missing one, but both beat discarding a good answer.
def _strip_unverified_citations(generation_response: GenerationResponse) -> None:
    answer = generation_response.answer
    if not answer:
        return

    valid_labels = {
        source.label
        for source in (generation_response.sources or [])
    }

    def _keep_verified(match: re.Match) -> str:
        cited_label = match.group(1)
        return match.group(0) if cited_label in valid_labels else ""

    generation_response.answer = _CITATION_PATTERN.sub(_keep_verified, answer)

def _validate_relevance(response: str, sources: list[CitedSource]) -> GenerationResponse | None:
    #Helper LLM (future)
    return None

def _check_safety(query: str) -> GenerationResponse | None:
    #Helper LLM (future)
    return None
