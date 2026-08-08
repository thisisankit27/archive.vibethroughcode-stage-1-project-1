"""Text checks shared by the input and output guardrails.

This module exists because the SAME question gets asked in two directions.

`input_guardrails` asks it of what the user typed. `output_guardrails` asks it of the
conversation summary our own model produced - because that summary is injected into every
later prompt, so a poisoned one persists across turns instead of dying with one request.

Keeping the keyword set in both modules would mean adding a phrase to one and forgetting
the other: a drift bug with a security consequence rather than a cosmetic one.

Note the naming. This is not "input policy" or "output policy" - it answers one question
that has no direction: **does this text contain something shaped like an instruction?**
What to DO about the answer is the caller's decision, and the two callers decide
differently - one rejects the request, the other discards the summary.
"""

import re

_FLAGGED_PHRASES = {
    "system prompt",
    "bypass",
    "system override",
    "developer mode",
    "ignore the previous rule",
    "print the above",
}

_INJECTION_PATTERN = re.compile(
    r"\b(" + "|".join(re.escape(phrase) for phrase in _FLAGGED_PHRASES) + r")\b",
    re.IGNORECASE,
)


def contains_injection_attempt(text: str | None) -> bool:
    """True if `text` contains instruction-like phrasing.

    Pure predicate - returns a bool, never a domain object. That is deliberate: a
    function that decided the CONSEQUENCE could only serve one of its two callers.
    """
    if not text:
        return False

    return bool(_INJECTION_PATTERN.search(text))
