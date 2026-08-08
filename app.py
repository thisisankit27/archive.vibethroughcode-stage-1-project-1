import time
from dataclasses import dataclass

import streamlit as st
from data.src.ingestion import ingest_documents
from data.src.metadata.metadata_catalog import MetadataCatalog
from data.src.models.GenerationResponse import GenerationResponse
from data.src.rag import ask_stream


# --------------------------------------------------
# Conversation record
# --------------------------------------------------
# One exchange: what was asked, and everything the pipeline produced in reply.
#
# This lives in app.py, not in data/src/, on purpose. A conversation is SESSION state -
# it belongs to one browser tab and dies with it. Nothing in the domain layer knows or
# needs to know that a previous question was ever asked; rag.py still answers each
# question in complete isolation.
#
# Teaching the RETRIEVER about previous turns is a different problem with a different
# owner - that is PR-13, Memory Architecture. Keeping the record here is what keeps the
# two PRs from bleeding into each other.
@dataclass
class ChatTurn:
    question: str
    response: GenerationResponse

    # PR-13. What it cost to fold this turn into the conversation summary.
    #
    # Kept OUT of response.token_usage deliberately. That field is the cost of answering
    # one question; adding a second call's tokens to it would make the per-turn "Prompt
    # Tokens" metric describe two different calls at once. Two costs, two fields - and
    # the sidebar reports them as two different things, because they are.
    summary_token_usage: dict | None = None

# --------------------------------------------------
# Typewriter rendering
# --------------------------------------------------
# The backend flushes in blocks of ~20 tokens, because that is the window it needs to
# guarantee a citation marker is never split across a flush. Rendered directly, those
# blocks land as visible bursts.
#
# This is a PRESENTATION problem, so it is fixed here and not by shrinking the buffer.
# Lowering FLUSH_FLOOR would smooth the render too - by shrinking the policy window and
# running the guardrails once per token. Never weaken a safety mechanism to fix how
# something looks.
#
# Pacing is adaptive rather than a fixed delay. Each block is spread over roughly the
# time the model took to produce it, so the typing speed tracks the model instead of
# guessing at it:
#   - model slow  -> we type slowly, no stall waiting for the next block
#   - model fast  -> blocks are already queued, wait ~0, delay clamps to the floor and
#                    the animation catches up
# Self-correcting, because falling behind makes the next measured wait smaller.

_SLICE = 3          # characters yielded per repaint; 1 is smoother but repaints 3x more
_MIN_DELAY = 0.002  # floor - stops it spinning when blocks are already buffered
_MAX_DELAY = 0.015  # ceiling - stops one slow block (or model warm-up) crawling
_FIRST_DELAY = 0.008  # used for block 1, which has no previous interval to measure


def typewriter(blocks):
    """Re-emit the backend's flushed blocks as a smooth character stream."""

    iterator = iter(blocks)

    while True:
        # Time spent inside next() is time the MODEL was working. Measuring it here -
        # rather than around the whole loop - keeps our own sleeping out of the number,
        # which would otherwise make the pacing self-referential.
        started_waiting = time.perf_counter()
        try:
            block = next(iterator)
        except StopIteration:
            break
        waited = time.perf_counter() - started_waiting

        if not block:
            continue

        # Spread this block's characters across the time the next one is expected to
        # take. First block has nothing to measure against, so use a sane default.
        per_char = _FIRST_DELAY if waited == 0 else waited / len(block)
        delay = min(max(per_char, _MIN_DELAY), _MAX_DELAY) * _SLICE

        for position in range(0, len(block), _SLICE):
            yield block[position:position + _SLICE]
            time.sleep(delay)

# --------------------------------------------------
# Page Configuration
# --------------------------------------------------
st.set_page_config(
    page_title="Knowledge Assistant",
    page_icon="🦈",
    layout="wide",
)

# --------------------------------------------------
# Session State
# --------------------------------------------------
if "knowledge_base" not in st.session_state:
    st.session_state.knowledge_base = None

if "last_upload_signature" not in st.session_state:
    st.session_state.last_upload_signature = None

# The conversation. Session state only - deliberately NOT persisted to disk.
#
# The band each value belongs to is the whole point of this PR:
#   persistent (disk)  storage/*.index, metadata_catalog.json  -> survives restart,
#                      shared by every session; that is why documents need uploading once
#   session (RAM)      this list                               -> dies with the tab
#   transient (a run)  the streamed text, filters              -> dies at end of script
#
# Documents are expensive to rebuild, so they live on disk. A conversation is cheap,
# private to one person, and stale the moment they leave - so it does not.
if "conversation" not in st.session_state:
    st.session_state.conversation = []

# PR-13. The running conversation summary - ONE value, not one per turn.
#
# It is a single key rather than a field on each ChatTurn because there is exactly one
# current summary. Storing a copy per turn would make "the current one" mean "whichever is
# in the last element", i.e. meaning implied by list position - the same fragility
# rejected in PR-11 when positional citation markers lost to a materialized mapping.
if "conversation_summary" not in st.session_state:
    st.session_state.conversation_summary = None


def conversation_totals(turns: list[ChatTurn]) -> dict:
    """Accumulated cost across the whole conversation.

    DERIVED, not stored. A running total kept in session state would be a second copy
    of a fact the turn list already holds - and the two would drift the first time a
    turn is removed or the history is cleared. Recomputing over a handful of turns is
    free; keeping two sources of truth in sync never is.
    """
    totals = {
        "input_tokens": 0,
        "output_tokens": 0,
        "latency": 0,
        "answered": 0,
        # PR-13: reported separately, never folded into the answer totals above. Keeping
        # memory is a real cost, but it is a cost of maintaining CONTEXT, not the cost of
        # answering the user's question. Merging them would hide roughly half the spend
        # inside a number labelled something else.
        "context_tokens": 0,
    }

    for turn in turns:
        summary_usage = turn.summary_token_usage or {}
        totals["context_tokens"] += summary_usage.get("total_tokens") or 0

        # Rejected turns never reached the model, so they contribute nothing but are
        # still counted as part of the conversation.
        if not turn.response.success:
            continue

        usage = turn.response.token_usage or {}
        totals["input_tokens"] += usage.get("input_tokens") or 0
        totals["output_tokens"] += usage.get("output_tokens") or 0
        totals["latency"] += turn.response.latency or 0
        totals["answered"] += 1

    return totals


def render_reply_details(response: GenerationResponse) -> None:
    """Everything under an assistant reply: sources, per-turn cost, chunks, metadata.

    Shared by both render paths - a turn replayed from history and a turn that has just
    finished streaming render identically below the answer text. Only the answer itself
    is animated, and only once.
    """
    if not response.success:
        return

    # Sources stay visible - they are part of the answer's credibility, not diagnostics -
    # but on ONE line instead of one line per source.
    if response.sources:
        st.caption(
            "Sources: "
            + "  ·  ".join(
                f"`[{source.label}]` {source.display_name}"
                for source in response.sources
            )
        )

    # Everything below is diagnostics. Collapsed by default: at three-plus turns the page
    # was mostly instrumentation, and the answers - the actual product - were the smallest
    # thing on screen.
    #
    # Tabs rather than more expanders because Streamlit does not allow an expander inside
    # an expander.
    with st.expander("ℹ️ Details"):

        cost_tab, chunks_tab, metadata_tab = st.tabs(
            ["Cost", "Retrieved Chunks", "Raw Metadata"]
        )

        with cost_tab:
            # What THIS question cost. The running conversation total is in the sidebar.
            token_usage = response.token_usage or {}
            cost_column_1, cost_column_2, cost_column_3 = st.columns(3)

            with cost_column_1:
                st.metric("Prompt Tokens", token_usage.get("input_tokens", "-"))

            with cost_column_2:
                st.metric("Completion Tokens", token_usage.get("output_tokens", "-"))

            with cost_column_3:
                st.metric(
                    "Latency",
                    f"{response.latency / 1_000_000:.0f} ms" if response.latency else "-",
                )

            st.caption(f"Finish reason: `{response.finish_reason}`")
            st.caption(
                "Answered using Hybrid Retrieval (Dense + BM25 + RRF) with verified citations."
            )

        with chunks_tab:
            st.caption(
                f"{len(response.sources or [])} fused chunks "
                "(Reciprocal Rank Fusion)."
            )

            for rank, source in enumerate(response.sources or [], start=1):
                document = source.document

                st.markdown(f"**`[{source.label}]` {source.display_name}** — fusion rank #{rank}")
                st.write(document.page_content)

                chunk_column_1, chunk_column_2 = st.columns(2)

                with chunk_column_1:
                    st.caption("**Document ID**")
                    st.code(document.metadata.get("document_id", "-"))

                with chunk_column_2:
                    st.caption("**Chunk ID**")
                    st.code(source.chunk_id or "-")

                st.divider()

        with metadata_tab:
            st.json(response.metadata)


# --------------------------------------------------
# Sidebar
# --------------------------------------------------
with st.sidebar:
    st.header("🗺️ Project Roadmap")

    st.success("✅ Week 1 — Core RAG (PR-1 → PR-6)")
    st.success("✅ Week 2 — Deepen RAG (PR-7 → PR-9)")
    st.success("✅ Week 3 — LCEL & Citations (PR-10 → PR-11a)")

    st.info("🚧 Week 4 — Production Readiness (PR-12a → PR-12)")

    st.divider()

    # --------------------------------------------------
    # Conversation cost
    # --------------------------------------------------
    # Accumulated across every answered turn in this session. Recomputed each run from
    # the turn list rather than incremented, so it can never disagree with the history
    # actually on screen.
    st.subheader("💬 Conversation")

    totals = conversation_totals(st.session_state.conversation)

    st.metric("Turns", len(st.session_state.conversation))

    sidebar_column_1, sidebar_column_2 = st.columns(2)

    with sidebar_column_1:
        st.metric("Prompt Tokens", totals["input_tokens"])

    with sidebar_column_2:
        st.metric("Completion Tokens", totals["output_tokens"])

    st.metric(
        "Total Tokens",
        totals["input_tokens"] + totals["output_tokens"],
    )

    st.caption(
        f"Cumulative generation time: {totals['latency'] / 1_000_000_000:.1f}s "
        f"across {totals['answered']} answered turn(s)."
    )

    # A separate line, not added to the totals above. This is what it costs to REMEMBER,
    # as distinct from what it costs to answer - and seeing the two side by side is the
    # honest picture of what conversation memory is worth.
    st.caption(f"🧠 Context upkeep: {totals['context_tokens']} tokens")

    if st.session_state.conversation_summary:
        with st.expander("🧠 What the assistant remembers"):
            st.caption(st.session_state.conversation_summary)

    # Both keys reset together. The summary describes the conversation, so keeping it
    # after clearing the history would leave a phantom memory of turns that no longer
    # exist - and it would keep steering retrieval toward topics the user just discarded.
    if st.button("🗑️ Clear Conversation", use_container_width=True):
        st.session_state.conversation = []
        st.session_state.conversation_summary = None
        st.rerun()
# --------------------------------------------------
# Main Page
# --------------------------------------------------
st.title("🦈 Knowledge Assistant")
st.caption("Build your own private knowledge base using AI.")

st.divider()

# --------------------------------------------------
# Upload Section
# --------------------------------------------------
st.subheader("📚 Build Knowledge Base")

# --------------------------------------------------
# What is already indexed  (corpus scope, read from disk)
# --------------------------------------------------
# Read ONCE per run and reused by the retrieval filters further down, so the two panels
# can never disagree about what exists.
#
# This block is deliberately OUTSIDE the `if st.session_state.knowledge_base:` branch
# below. That branch is an upload RECEIPT - "this upload produced N chunks in X seconds"
# - and a receipt correctly disappears when you leave. But two facts were trapped inside
# it that are not about the upload at all: what documents exist, and how large the corpus
# is. Those belong to the index on disk, which outlives every session.
#
# The symptom was a returning user opening the app, seeing an empty uploader, and having
# no idea their knowledge base was already built - while the chat below answered
# questions from it perfectly.
#
#   facts about an UPLOAD EVENT  -> session state, shown as a receipt
#   facts about the CORPUS       -> disk, shown on every run
indexed_documents = MetadataCatalog.list_documents()

if indexed_documents:
    with st.expander(
        f"🗂️ Knowledge base contains **{len(indexed_documents)} document(s)**",
        expanded=False,
    ):
        for indexed_document in indexed_documents:
            st.markdown(f"- {indexed_document['display_name']}")

        st.caption(
            "Indexed on disk (FAISS + BM25). These persist across restarts — "
            "re-uploading is only needed for new documents."
        )
else:
    st.caption("No documents indexed yet. Upload one or more files to get started.")

files = st.file_uploader(
    "Upload PDF or Markdown documents",
    type=["pdf", "md"],
    accept_multiple_files=True,
)

if st.button("Build Knowledge Base"):

    if not files:
        st.warning("Please upload one or more documents.")
        st.stop()

    upload_signature = tuple(
        (file.name, file.size)
        for file in files
    )

    if st.session_state.last_upload_signature != upload_signature:

        (
            chunks,
            dimension,
            elapsed,
            knowledge_base_size,
            sparse_stats,
        ) = ingest_documents(files)

        st.session_state.knowledge_base = {
            "chunks": chunks,
            "dimension": dimension,
            "elapsed": elapsed,
            "knowledge_base_size": knowledge_base_size,
            "sparse_stats": sparse_stats,
        }

        st.session_state.last_upload_signature = upload_signature

if st.session_state.knowledge_base:

    kb = st.session_state.knowledge_base

    chunks = kb["chunks"]
    dimension = kb["dimension"]
    elapsed = kb["elapsed"]
    knowledge_base_size = kb["knowledge_base_size"]
    sparse_stats = kb["sparse_stats"]

    st.success(
        f"Successfully indexed **{len(chunks)} chunks** into the knowledge base."
    )

    st.info(
        "✅ Your knowledge base has been built using both dense (FAISS) and sparse (BM25) indexing."
    )

    # --------------------------------------------------
    # Metrics
    # --------------------------------------------------

    col1, col2, col3, col4 = st.columns(4)

    with col1:
        st.metric(
            "Chunks Generated",
            len(chunks),
        )

    with col2:
        st.metric(
            "Knowledge Base Size",
            knowledge_base_size,
        )

    with col3:
        st.metric(
            "Embedding Time",
            f"{elapsed:.3f}s",
        )

    with col4:
        st.metric(
            "Vocabulary Size",
            sparse_stats["vocabulary_size"],
        )

    st.divider()

    selected_chunk = st.number_input(
        "Preview Indexed Chunk",
        min_value=1,
        max_value=len(chunks),
        value=1,
    )

    chunk = chunks[selected_chunk - 1]

    with st.expander("📄 Chunk Content", expanded=True):
        st.write(chunk.page_content)

    with st.expander("🏷️ Chunk Metadata"):
        st.json(chunk.metadata)

    with st.expander("📊 Knowledge Base Information"):

        st.markdown(
            f"""
            **Embedding Model**
            - embeddinggemma:latest

            **Vector Store**
            - FAISS (L2 Distance)

            **Embedding Dimension**
            - {dimension}

            **Chunks Indexed This Upload**
            - {len(chunks)}

            **Embedding Time**
            - {elapsed:.3f} seconds
            """
        )

st.divider()

# --------------------------------------------------
# Metadata Filters
# --------------------------------------------------
st.subheader("🔍 Retrieval Filters")

# Reuses the list read at the top of the page rather than reading the catalog a second
# time - one read per run, so the upload panel and the filter list are guaranteed to be
# describing the same corpus.
selected_documents = st.multiselect(
    "Limit retrieval to specific documents",
    options=indexed_documents,
    default=indexed_documents,
    format_func=lambda document: document["display_name"],
)

filters = {
    "document_ids": [
        document["document_id"]
        for document in selected_documents
    ]
}

st.divider()

# --------------------------------------------------
# Conversation
# --------------------------------------------------
st.subheader("💬 Conversation")

if not st.session_state.conversation:
    st.caption("Ask a question below to start the conversation.")

# ---- REPLAY -----------------------------------------------------------------------
# Every past turn, re-rendered from session state on EVERY run.
#
# This loop is what fixes the defect this PR exists for. Previously the answer was a
# local variable inside `if st.button(...)`, so any widget interaction - changing the
# document filter, moving the chunk preview - reran the script, found the button False,
# and the answer vanished. Rendering from state instead of from a local means the screen
# is a function of what is remembered, not of what just happened.
#
# Rendered with st.markdown, NOT the typewriter: replaying the animation on every rerun
# would look broken and cost seconds. Only the newest reply is ever animated, and only
# once - the transition from "being generated" to "history" is exactly the transition
# from transient state to session state.
for past_turn in st.session_state.conversation:

    with st.chat_message("user"):
        st.markdown(past_turn.question)

    with st.chat_message("assistant"):
        if past_turn.response.success:
            st.markdown(past_turn.response.answer)
        else:
            # Rejections are shown, not hidden. A guardrail refusal is a real thing that
            # happened in this conversation, and silently dropping it would make the
            # history a misleading account of the session.
            st.error(past_turn.response.message)

        render_reply_details(past_turn.response)

# ---- NEW TURN ---------------------------------------------------------------------
# chat_input returns the submitted text only on the run where it was submitted, and
# clears itself afterwards - so this block runs once per question, never on a replay.
question = st.chat_input("Ask something about your uploaded documents")

if question:

    with st.chat_message("user"):
        st.markdown(question)

    with st.chat_message("assistant"):

        # Returns immediately. No model call has happened yet - generation starts when
        # write_stream begins pulling from the token iterator.
        #
        # The summary passed in was produced at the END of the previous turn, so it is
        # already sitting in memory. Conversation memory therefore costs nothing at
        # time-to-first-token - the work was done a turn ago, off the critical path.
        stream = ask_stream(question, filters, st.session_state.conversation_summary)

        # A pre-generation rejection (empty question, prompt injection, no context) has
        # already populated `response` and will yield no tokens. Checking here keeps an
        # empty stream from rendering an empty bubble.
        if stream.response is None:
            # The ONLY animated render in the whole page. typewriter() smooths the
            # cadence of the backend's buffered flushes; it changes nothing about the
            # text, the order, or the sanitizing already applied.
            st.write_stream(typewriter(stream.tokens))

        # Readable only now - _stream_tokens assembles it after the final flush.
        response = stream.response

        # The ordering consequence of streaming: an output validator can only reject
        # once the text is already on screen, so the error appears BELOW an answer the
        # user has read. Documented in week-4-AI-Assistant.md as the honest cost of
        # streaming rather than something to paper over.
        if not response.success:
            st.error(response.message)

        render_reply_details(response)

    # PROMOTION: transient -> session. Appending AFTER rendering is what prevents a
    # double render - the replay loop above already ran this pass with the old history.
    # Replace the one current summary. On any path that did not produce an accepted new
    # one - a guardrail rejection, a summary that failed validation - rag.py hands back
    # the value we passed in, so this assignment is a harmless no-op rather than a wipe.
    st.session_state.conversation_summary = stream.summary

    st.session_state.conversation.append(
        ChatTurn(
            question=question,
            response=response,
            summary_token_usage=stream.summary_token_usage,
        )
    )

    # Then immediately re-run, and this is the important part.
    #
    # Streamlit executes top to bottom. The sidebar - including the accumulated
    # conversation cost - rendered near the TOP of this script, BEFORE this turn was
    # appended. So the totals on screen describe the conversation as it was one question
    # ago. Nothing recomputes them, because nothing re-executes.
    #
    # This is the defining property of the whole PR stated as a rule:
    #
    #   THE PAGE IS A FUNCTION OF STATE.
    #   Anything rendered before the state changed is stale by definition.
    #
    # Re-running makes the page a function of the CURRENT state: sidebar totals include
    # this turn, and the answer just streamed is replayed statically from history like
    # every other turn. It also clears the dimmed leftovers Streamlit shows while a long
    # blocking render is in progress.
    #
    # This costs nothing - no model call. The turn is already in memory; the rerun only
    # re-renders from it.
    st.rerun()

st.divider()

# --------------------------------------------------
# Footer
# --------------------------------------------------
st.caption("Built in Public ❤️ | Week 4 | Streaming & Conversation State")