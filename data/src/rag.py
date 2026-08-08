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
    sanitize_summary,
    strip_unverified_citations,
    validate_output,
    validate_summary,
)
from data.src.observability import end_turn, get_logger, log_event, stage, start_turn
from data.src.resilience import DependencyError
from data.src.summarization_service import SummarizationService

_logger = get_logger("rag")

# PR-14a: these moved to config.py. Re-exported here so every call site in this module
# keeps reading like a local constant.
#
#   TOP_K        retrieval breadth
#   FLUSH_FLOOR  how many chunks accumulate before a flush is considered (a UX floor)
#   MARKER_MAX   how long an unmatched "[" may be held before it is ruled out as a
#                citation. NOT independently settable - it is derived from TOP_K, because
#                the longest valid marker is "[" + str(TOP_K) + "]". See config.py.
from data.src.config import FLUSH_FLOOR, MARKER_MAX, TOP_K


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

    # PR-13. The conversation summary AFTER this turn, and what producing it cost.
    #
    # These live here rather than on GenerationResponse on purpose. GenerationResponse is
    # the answer to ONE question; a summary describes the whole conversation, has a
    # different lifetime, and would be meaningless on the rejection objects the guardrails
    # return. StreamedAnswer already means "everything this call produced", which is
    # exactly what these are.
    #
    # `summary` is seeded with the INCOMING summary, so every path that does not produce
    # an accepted new one - a guardrail rejection, a failed summary - leaves the caller's
    # memory untouched rather than wiping it.
    summary: str | None = None
    summary_token_usage: dict | None = None

    # PR-14b. Every event logged during this turn, in order.
    #
    # On StreamedAnswer rather than GenerationResponse for the same reason the summary is:
    # it describes the whole TURN - including the summarization that runs after the response
    # exists - and would be meaningless on the rejection objects guardrails return.
    #
    # MUTABLE and shared, not a snapshot. `_refresh_summary` appends to it after
    # `handle.response` has already been assigned, so a copy taken at that moment would
    # silently drop every summary event. Same lesson as PR-12's stale sidebar.
    trace: list = field(default_factory=list)


def _build_retrieval_query(summary: str | None, query: str) -> str:
    """The string retrieval actually searches on.

    THE PROBLEM. "What are his skills?" embeds to nothing useful and BM25 scores it on
    "what", "are", "his", "skills". The retriever runs BEFORE the prompt is built, so
    handing history to the model does not help it - by then the wrong chunks are fetched.

    THE FIX. Prepend the conversation summary, so the query carries the subject the user
    left implicit.

    WHY NOT RETRIEVE TWICE AND FUSE. fusion_service.py already does RRF over multiple
    result lists, so retrieving once on the question and once on the summary looks
    tempting. It is wrong here: RRF assumes its inputs are comparably-competent rankings
    of the same information need. On a follow-up, the question-only arm is KNOWN to be
    noise - and because RRF scores by reciprocal rank, a junk chunk ranked #1 in the bad
    arm scores about the same as a good chunk ranked #1 in the good arm. That promotes
    noise into the top-K at near-equal weight. Fusing is for two good retrievers, not for
    one good and one broken.

    KNOWN LIMITATION - topic change. The summary is 3 sentences, the question is a
    handful of words, so the summary dominates both the embedding and the BM25 term
    counts. That is exactly what a follow-up needs and exactly wrong when the user
    changes subject: turn 4 asking about RRF, after three turns about a resume, retrieves
    resume chunks. Accepted for now and clearing the conversation resets it. The fix, when
    it is worth its magic number, is to embed the question, cosine-compare it against the
    summary, and drop the summary below a threshold - roughly free, since the question's
    vector is computed for the dense arm anyway.
    """
    if not summary:
        return query

    return f"{summary}\n{query}"


def _retrieve_context(
    query: str,
    filters: dict,
    summary: str | None = None,
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

    # The RAW question, never the concatenated one. Passing summary+query here would break
    # the empty-question check and would reject the user for a poisoned summary they did
    # not write. See the note above validate_input.
    rejection = validate_input(query)
    if rejection:
        return None, rejection

    retrieval_query = _build_retrieval_query(summary, query)

    with stage(_logger, "retrieval", top_k=TOP_K):
        documents = RetrievalService.retrieve(retrieval_query, TOP_K, filters)

    # `summary_prefixed` is the signal for PR-13's documented topic-change limitation: when it
    # is True the retrieval query was dominated by the conversation summary, so a result set
    # that looks unrelated to the question has an explanation sitting right next to it.
    #
    # Chunk IDs, not chunk text - enough to see WHICH chunks came back and notice the same
    # irrelevant one appearing every time, without writing document content to a durable file.
    log_event(
        _logger,
        "retrieval.done",
        returned=len(documents),
        requested=TOP_K,
        summary_prefixed=bool(summary),
        filtered_documents=len(filters.get("document_ids", [])),
        chunk_ids=[document.metadata.get("chunk_id") for document in documents],
    )

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


def ask(query: str, filters: dict, summary: str | None = None) -> GenerationResponse:
    """Blocking path. Kept as the non-streaming peer.

    Accepts a summary for parity but does NOT produce one - a caller with no stream to
    defer behind would pay for summarization synchronously, and this path exists for
    testing the pipeline without a UI.
    """

    documents, rejection = _retrieve_context(query, filters, summary)
    if rejection:
        return rejection

    try:
        generation_response = GenerationService.generate_answer(query, documents, summary)
    except DependencyError as error:
        return _degraded_response(error, None)

    rejection = validate_output(generation_response)
    if rejection:
        return rejection

    return generation_response


def ask_stream(
    query: str,
    filters: dict,
    summary: str | None = None,
) -> StreamedAnswer:
    """Streaming path. Returns immediately - no model call has happened yet.

    Generation begins when the caller starts consuming `handle.tokens`.

    `summary` is the conversation summary produced by the PREVIOUS turn. It is already in
    hand when this call starts, which is the whole reason conversation memory costs
    nothing at time-to-first-token: the expensive part happened last turn.
    """

    # Begin collecting this turn's events. The list is handed straight to the handle, so
    # everything logged from here until end_turn() lands in handle.trace - at any call depth,
    # without a single service signature growing an argument for it.
    trace, trace_token = start_turn()

    # Seeded with the incoming summary so every early-return path leaves memory intact.
    handle = StreamedAnswer(summary=summary, trace=trace)

    log_event(
        _logger,
        "turn.start",
        query_chars=len(query),
        has_summary=bool(summary),
        streaming=True,
    )

    documents, rejection = _retrieve_context(query, filters, summary)
    if rejection:
        # Rejected before generation. No tokens will ever arrive and the response is
        # already final, so hand it over now. `tokens` stays the empty iterator, and
        # the UI's "consume then check" flow works without a special case.
        handle.response = rejection

        log_event(_logger, "turn.end", outcome="rejected", reason=rejection.reason)

        # This path never enters the generator, so it must close the turn itself. Leaving it
        # open would let the NEXT turn's events append to this turn's trace - the exact leak
        # that made threading.local() the wrong tool.
        end_turn(trace_token)
        return handle

    # stream_answer only BUILDS the lazy iterator, so a dead Ollama does not raise here - it
    # raises on the first next(), inside _stream_tokens, which is where it is handled.
    sources, chunks = GenerationService.stream_answer(query, documents, summary)
    handle.tokens = _stream_tokens(handle, chunks, sources, query, summary, trace_token)

    return handle


def _degraded_response(
    error: DependencyError,
    sources: list[CitedSource] | None,
) -> GenerationResponse:
    """The LLM is unreachable but retrieval already succeeded.

    This is the PR-15 decision that matters, and it is not "show an error". Retrieval is local
    - FAISS and BM25 are files on disk - so when Ollama dies we still know the three passages
    most relevant to the question. The retrieval half of RAG keeps working when the generation
    half does not.

    So the response carries `sources`, and the UI renders them as passages the user can read
    themselves. Degraded, honest, and genuinely useful - not a consolation error page.

    Note the rule this follows: degrade when a partial result is still useful AND honest. There
    is no partial ANSWER to offer, so we do not invent one; there are real passages, so we
    offer those and say plainly where they came from.
    """
    return GenerationResponse(
        success=False,
        reason=error.reason,
        message=error.message,
        sources=sources,
    )


def _refresh_summary(
    handle: StreamedAnswer,
    previous_summary: str | None,
    query: str,
    answer: str,
) -> None:
    """The deferred WRITE path: fold this turn into the running summary.

    Runs after the final token has been flushed, so the user is already reading their
    answer while this executes. It is DEFERRED, not asynchronous - Streamlit is
    synchronous and single-threaded per session, and a real thread would have no
    ScriptRunContext. Calling it "background" would be a lie about the mechanism; what is
    true, and what matters, is that it is off the critical path of every question.

    Sanitize, then validate, then accept - the two contracts kept separate, as everywhere
    else in the guardrails.
    """

    # DEGRADE, never fail. The user already has their answer; a summarization outage must not
    # retroactively turn a successful turn into an error. Memory simply stops advancing - the
    # same consequence PR-13 chose when a summary fails validation, now reached by a second
    # route. One outcome, one behaviour.
    try:
        candidate, usage = SummarizationService.summarize(previous_summary, query, answer)
    except DependencyError as error:
        log_event(
            _logger,
            "summary.skipped",
            reason=error.reason,
            attempts=error.attempts,
        )
        return

    handle.summary_token_usage = usage

    candidate = sanitize_summary(candidate)

    if validate_summary(candidate):
        handle.summary = candidate
    # Otherwise handle.summary keeps the value it was seeded with. Memory stops advancing
    # rather than disappearing: the conversation keeps what it already knew, and the user
    # sees nothing go wrong. Clearing it instead would turn one bad summary into sudden
    # amnesia mid-conversation.


def _stream_tokens(
    handle: StreamedAnswer,
    chunks: Iterator[AIMessageChunk],
    sources: list[CitedSource],
    query: str,
    previous_summary: str | None,
    trace_token=None,
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
    emitted = False         # has any text reached the user yet?

    # PR-15. `.stream()` is LAZY, so the connection to Ollama is not made when ask_stream()
    # returns - it happens on the first next() of this loop, which Streamlit performs from
    # inside st.write_stream. Without this try, a dead Ollama surfaces as a traceback rendered
    # underneath the user's own question bubble.
    #
    # The generator must not raise. Its caller is a UI rendering function, and a UI cannot do
    # anything sensible with an httpx exception.
    try:
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
            emitted = True

            pending = pending[safe:]
            held = 0

        # END OF STREAM: flush unconditionally, whatever the predicate says. A "[" still
        # unmatched at this point is literal text - no tokens remain that could close it.
        # Skipping this would silently swallow the tail of the answer.
        if pending:
            yield strip_unverified_citations(pending, sources)
            emitted = True

    except DependencyError as error:
        # Retrieval SUCCEEDED - FAISS and BM25 are local files - so `sources` holds the
        # passages this question actually matched. Hand them over instead of an error page.
        handle.response = _degraded_response(error, sources)

        log_event(
            _logger,
            "turn.end",
            outcome="degraded",
            reason=error.reason,
            attempts=error.attempts,
            partial_output=emitted,
            sources_offered=len(sources),
        )

        # No summarization: there is no answer to fold into memory. Memory is untouched, so
        # the next question still has whatever context the conversation had before.
        if trace_token is not None:
            end_turn(trace_token)
        return

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

    # ---- DEFERRED WRITE PATH ----------------------------------------------------------
    # Everything above this line was on the critical path. Nothing below it is: the last
    # token has been yielded, so the user has their complete answer on screen.
    #
    # Only successful turns are summarized. A guardrail rejection has no answer worth
    # remembering, and folding "the user asked something we refused" into memory would
    # carry the refusal forward into every later prompt.
    if handle.response.success:
        _refresh_summary(handle, previous_summary, query, handle.response.answer)

    usage = handle.response.token_usage or {}

    log_event(
        _logger,
        "turn.end",
        outcome="answered" if handle.response.success else "rejected",
        reason=handle.response.reason,
        input_tokens=usage.get("input_tokens"),
        output_tokens=usage.get("output_tokens"),
        generation_ms=round(handle.response.latency / 1_000_000) if handle.response.latency else None,
        answer_chars=len(handle.response.answer or ""),
    )

    # Close the turn AFTER summarization, so summary events are inside this trace and not
    # leaking into the next one.
    if trace_token is not None:
        end_turn(trace_token)
