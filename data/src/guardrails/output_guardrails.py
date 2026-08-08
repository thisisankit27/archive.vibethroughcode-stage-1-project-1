import re
from data.src.guardrails.text_policy import contains_injection_attempt
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
#
# PR-12a split this into a pure function plus an adapter. Reason: the streaming path
# has no GenerationResponse yet when it needs to sanitize - it only has a string. Rather
# than duplicate the regex logic, the logic moved to a function that takes text and
# returns text, and the original signature became a thin wrapper over it.
# Same move as _format_documents in PR-10: if it doesn't need the object, don't take it.
def strip_unverified_citations(text: str | None, sources: list[CitedSource] | None) -> str | None:
    """Remove [n] markers whose label was never issued for this request.

    Pure: text in, text out. No framework types, no domain object, no I/O - so it is
    unit-testable with a plain assert and callable from both the streaming and the
    non-streaming path.

    Verification is deterministic set membership, not an LLM call. Citation *existence*
    is structurally checkable in code; citation *supportiveness* is judgment and stays
    in _validate_relevance.
    """
    if not text:
        return text

    valid_labels = {
        source.label
        for source in (sources or [])
    }

    def _keep_verified(match: re.Match) -> str:
        cited_label = match.group(1)
        return match.group(0) if cited_label in valid_labels else ""

    return _CITATION_PATTERN.sub(_keep_verified, text)


def _strip_unverified_citations(generation_response: GenerationResponse) -> None:
    """Adapter: applies the sanitizer to a GenerationResponse, in place.

    Exists so validate_output()'s call site is unchanged. Still a sanitizer, not a
    validator - it repairs and returns None, it never rejects.
    """
    generation_response.answer = strip_unverified_citations(
        generation_response.answer,
        generation_response.sources,
    )

# --------------------------------------------------
# Conversation summary (PR-13)
# --------------------------------------------------
# The summary is model OUTPUT, which is why it is governed here rather than in
# input_guardrails. It is also the only piece of model output that OUTLIVES its request -
# it is injected into every later prompt - so it is the one thing worth checking twice.
#
# Kept as two functions with the two contracts this module already distinguishes:
#   sanitize_summary  repairs, always returns text
#   validate_summary  judges, returns a verdict
# rag.py sequences them: sanitize, then validate, then accept or keep the previous one.


def sanitize_summary(summary: str | None) -> str | None:
    """Strip citation markers from a summary.

    Citation labels are REQUEST-scoped by design (PR-11b): [1] means whatever chunk was
    labelled 1 for one prompt. A summary outlives its request, so a marker that leaked
    into it would mean a different document on the next turn - silently wrong attribution,
    which is exactly the failure mode CitedSource's materialized mapping exists to prevent.

    Reuses _CITATION_PATTERN with no valid labels, i.e. remove every marker.
    """
    if not summary:
        return summary

    return _CITATION_PATTERN.sub("", summary)


def validate_summary(summary: str | None) -> bool:
    """Is this summary fit to inject into the next prompt?

    A verdict, not a repair - and note the consequence is the caller's to choose. rag.py
    responds to False by keeping the PREVIOUS summary rather than clearing memory: the
    conversation stops advancing instead of losing what it already knew.
    """
    if not summary or not summary.strip():
        return False

    # Same rule the input guardrail applies to the user, different consequence.
    if contains_injection_attempt(summary):
        return False

    return True


def _validate_relevance(response: str, sources: list[CitedSource]) -> GenerationResponse | None:
    #Helper LLM (future)
    return None

def _check_safety(query: str) -> GenerationResponse | None:
    #Helper LLM (future)
    return None
