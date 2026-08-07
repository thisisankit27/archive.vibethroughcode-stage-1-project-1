"""Orchestration layer.

Owns the ORDER in which guardrails, retrieval, and generation run - and, as of PR-12a,
how a streamed answer is buffered before it reaches the UI.

It does not own retrieval strategy (RetrievalService), prompt composition
(GenerationService), or answering policy (the guardrail modules). Plain Python
throughout: no Runnables, no framework types leaking in. INVARIANT #1.
"""

from collections.abc import Iterator
from dataclasses import dataclass, field

from langchain_core.documents import Document
from langchain_core.messages import AIMessageChunk

from data.src.generation_service import GenerationService
from data.src.models.CitedSource import CitedSource
from data.src.models.GenerationResponse import GenerationResponse
from data.src.retriever.retrieval_service import RetrievalService
from data.src.guardrails.input_guardrails import validate_input
from data.src.guardrails.context_guardrails import validate_context
from data.src.guardrails.output_guardrails import (
    strip_unverified_citations,
    validate_output,
)

TOP_K = 3

# --- Streaming buffer configuration ------------------------------------------------
# Both are tuning knobs rather than behaviour, so both are PR-14a candidates.

# How many content chunks to accumulate before considering a flush to the UI.
# A FLOOR, not a target - the boundary rule below can still hold a flush back.
#   1        -> best time-to-first-token, but a guardrail pass per token and a
#               citation marker split on almost every answer
#   ~20      -> markers usually intact, buffering imperceptible to the reader
#   ~200     -> good policy window, but TTFT approaches not streaming at all
#   no limit -> you have reinvented .invoke()
FLUSH_FLOOR = 20

# The longest an unmatched "[" may be held before we decide it is not a citation.
#
# This bound comes from the grammar, not from taste: a valid marker is
# "[" + digits + "]", so with TOP_K = 3 the longest possible marker is "[3]" - three
# characters. Eight leaves room for a two-digit TOP_K plus slack.
#
# Past that, the bracket is ordinary text (documents contain "[note]", code samples,
# footnote syntax), and continuing to wait for a "]" that will never arrive would
# stall the stream indefinitely.
MARKER_MAX = 8


@dataclass
class StreamedAnswer:
    """Handle for one streaming answer.

    The caller needs two things out of a single operation: the text as it arrives,
    and the finished domain object. A generator can only deliver the first, so the
    second would otherwise have to be smuggled out through a mutable argument. This
    object makes both explicit and typed.

    Consumption contract:
        1. iterate `tokens` to completion  (st.write_stream does this)
        2. THEN read `response`

    `response` is None until the stream is exhausted - except when the request was
    rejected before generation started, in which case `tokens` is empty and
    `response` holds the rejection immediately. That makes the UI's code path
    identical for both cases: consume the stream, then check response.success.
    """

    tokens: Iterator[str] = field(default_factory=lambda: iter(()))
    response: GenerationResponse | None = None


def _retrieve_context(
    query: str,
    filters: dict,
) -> tuple[list[Document] | None, GenerationResponse | None]:
    """The three steps ask() and ask_stream() share: guard, retrieve, guard.

    Extracted in PR-12a. Streaming is a peer of ask(), not a variant of it, and two
    peers copying the same prefix means two places to edit when input guardrails
    change - one of which will eventually be missed.

    Returns (documents, None) on success or (None, rejection) when a guardrail says
    no. A tuple rather than an exception because a rejection is an EXPECTED outcome:
    the system is working correctly when it refuses. Exceptions for expected control
    flow hide the second path from the signature.
    """

    rejection = validate_input(query)
    if rejection:
        return None, rejection

    documents = RetrievalService.retrieve(query, TOP_K, filters)

    rejection = validate_context(query, documents)
    if rejection:
        return None, rejection

    return documents, None


def _safe_flush_point(pending: str) -> int:
    """How many characters of `pending` can be sent to the UI without splitting a
    citation marker. Everything before the returned index is safe.

    WHY THIS EXISTS
    A marker does not arrive as a marker. It arrives as "[", then "1", then "]",
    possibly in three separate chunks. Flush between them and the sanitizer sees
    "[1" - which its regex does not match - so an unverified marker is flushed
    unrepaired and is never looked at again. The user is shown a citation that
    resolves to nothing, which is exactly the defect PR-11c exists to prevent.

    Buffering alone does not fix this. It makes the split rarer - only when a marker
    straddles a buffer boundary - and a bug that fires one time in thirty is worse
    than one that fires every time, because it ships.

    This is the same problem as decoding UTF-8 from a socket: never flush half a
    multi-byte sequence. Here the "sequence" is "[" ... "]".

    Pure function - no model, no I/O - so it is testable on its own.
    """

    open_bracket = pending.rfind("[")

    # No bracket at all: nothing can be split.
    if open_bracket == -1:
        return len(pending)

    # The last bracket already has its closer, so no marker is mid-flight.
    if "]" in pending[open_bracket:]:
        return len(pending)

    # Unmatched, but too much text has followed for it to still be a marker.
    # Treat it as literal text rather than holding the buffer hostage forever.
    if len(pending) - open_bracket > MARKER_MAX:
        return len(pending)

    # A marker is genuinely in progress. Flush everything BEFORE it and keep the
    # fragment. Note this flushes the prefix rather than holding the whole buffer -
    # holding everything would cost time-to-first-token for no extra safety.
    return open_bracket


def ask(query: str, filters: dict) -> GenerationResponse:
    """Blocking path. Unchanged behaviour; kept as the non-streaming peer."""

    documents, rejection = _retrieve_context(query, filters)
    if rejection:
        return rejection

    generation_response = GenerationService.generate_answer(query, documents)

    rejection = validate_output(generation_response)
    if rejection:
        return rejection

    return generation_response


def ask_stream(query: str, filters: dict) -> StreamedAnswer:
    """Streaming path. Returns immediately - no model call has happened yet.

    Generation begins when the caller starts consuming `handle.tokens`.
    """

    handle = StreamedAnswer()

    documents, rejection = _retrieve_context(query, filters)
    if rejection:
        # Rejected before generation. No tokens will ever arrive and the response is
        # already final, so hand it over now. `tokens` stays the empty iterator, and
        # the UI's "consume then check" flow works without a special case.
        handle.response = rejection
        return handle

    sources, chunks = GenerationService.stream_answer(query, documents)
    handle.tokens = _stream_tokens(handle, chunks, sources)

    return handle


def _stream_tokens(
    handle: StreamedAnswer,
    chunks: Iterator[AIMessageChunk],
    sources: list[CitedSource],
) -> Iterator[str]:
    """Buffer the model's chunks, sanitize each flush, and assemble the final
    response once the stream ends.

    This is the heart of PR-12a. Streaming is not "token -> screen", it is
    "token -> policy -> screen": you cannot run policy over data you have already
    flushed, so a window is held back.
    """

    pending = ""            # received, not yet safe or large enough to flush
    accumulated = None      # merged message - carries the metadata at the end
    held = 0                # content chunks since the last flush

    for chunk in chunks:
        # LangChain accumulates a streamed message by ADDING chunks together. The
        # merged object is what finally carries response_metadata and usage_metadata,
        # which arrive only on the last chunk - so token counts, finish reason and
        # latency are simply not knowable until the stream is over.
        accumulated = chunk if accumulated is None else accumulated + chunk

        # Some chunks carry only metadata and no text.
        if not chunk.content:
            continue

        pending += chunk.content
        held += 1

        # FLOOR: not enough text yet to be worth a render pass.
        if held < FLUSH_FLOOR:
            continue

        # BOUNDARY: how much of what we hold is safe to release.
        safe = _safe_flush_point(pending)

        # A marker is in flight at the very start of the buffer, so there is no safe
        # prefix at all. Wait for more tokens rather than splitting it. MARKER_MAX
        # guarantees this cannot loop forever.
        if safe == 0:
            continue

        # Sanitize every flush. This is only CORRECT because _safe_flush_point
        # guarantees the slice contains no partial marker - the two decisions are
        # coupled, and weakening the boundary rule silently reintroduces the leak.
        yield strip_unverified_citations(pending[:safe], sources)

        pending = pending[safe:]
        held = 0

    # END OF STREAM: flush unconditionally, whatever the predicate says. A "[" still
    # unmatched at this point is literal text - no tokens remain that could close it.
    # Skipping this would silently swallow the tail of the answer.
    if pending:
        yield strip_unverified_citations(pending, sources)

    # Only now does a whole answer exist, so only now can whole-answer work run.
    response = GenerationService.build_response(accumulated, sources)

    # validate_output re-runs the sanitizer over the complete text. That is deliberate,
    # not redundant: `response.answer` is rebuilt from the RAW chunks, so it still
    # holds any markers that were stripped from what the user saw. Running it again
    # keeps the stored answer and the displayed answer in agreement.
    #
    # The validators inside it (empty, safety) can still REJECT here - but the tokens
    # have already been shown. That is the trade-off streaming makes, and it is not
    # fixable by clearing the screen: this UI could hide the text, an HTTP API could
    # not un-send the bytes. Hard blocks belong on the INPUT side; output-side
    # judgment is a flag after the fact, not a gate.
    rejection = validate_output(response)

    handle.response = rejection or response
