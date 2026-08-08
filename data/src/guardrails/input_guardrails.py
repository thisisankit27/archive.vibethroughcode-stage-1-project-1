from data.src.guardrails.text_policy import contains_injection_attempt
from data.src.models.GenerationResponse import GenerationResponse

# NOTE (PR-13): this runs on the RAW user question only, never on the question with the
# conversation summary concatenated. Two reasons:
#   1. _check_empty_query would stop working - "summary" + "" is never empty, so a blank
#      question would sail through from turn 2 onward.
#   2. It would blame the user for the machine's contamination. A poisoned summary would
#      reject a perfectly innocent question, with a message the user cannot act on, and
#      would keep doing so on every subsequent question - a permanently wedged session.
# The summary is checked instead by validate_summary() in output_guardrails, where the
# consequence is "discard the summary", not "reject the user".
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
    # The pattern moved to guardrails/text_policy.py in PR-13 so the summary check can
    # use the identical rule. Here the consequence is REJECT: the user typed it, so the
    # user can rephrase it.
    if contains_injection_attempt(query):
        return GenerationResponse(
                success=False,
                reason="PROMPT_INJECTION",
                message="Your request appears to contain prompt injection instructions."
            )

    return None