import re
from data.src.models.GenerationResponse import GenerationResponse

def validate_input(query: str) -> GenerationResponse | None:
    response = _check_empty_query(query)
    if response:
        return response
    
    response = _check_prompt_injection(query)
    if response:
        return response

    return None

def _check_empty_query(query: str) -> GenerationResponse | None:
    if not query.strip():
        return GenerationResponse(
                success=False,
                reason="EMPTY_QUERY",
                message="Please enter a question."
            )

    return None

def _check_prompt_injection(query: str) -> GenerationResponse | None:
    flagged_keywords = {
        "system prompt",
        "bypass",
        "system override",
        "developer mode",
        "ignore the previous rule",
        "print the above"
    }
    pattern_combined = r"\b(" + "|".join(re.escape(word) for word in flagged_keywords) + r")\b"
    regex_searcher = re.compile(pattern_combined, re.IGNORECASE)

    if regex_searcher.search(query):
        return GenerationResponse(
                success=False,
                reason="PROMPT_INJECTION",
                message="Your request appears to contain prompt injection instructions."
            )

    return None