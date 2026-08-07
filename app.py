import time

import streamlit as st
from data.src.ingestion import ingest_documents
from data.src.metadata.metadata_catalog import MetadataCatalog
from data.src.rag import ask_stream

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


# --------------------------------------------------
# Sidebar
# --------------------------------------------------
with st.sidebar:
    st.header("🗺️ Project Roadmap")

    st.success("✅ Week 1 — Core RAG (PR-1 → PR-6)")

    st.success("✅ Week 2 — Deepen RAG (PR-7 → PR-9)")
    st.success("✅ Week 3 — LCEL (PR-10 → PR-11)")

    st.info("🔜 Week 4 — Production Readiness")

    st.divider()

    st.subheader("Week 3 Progress")
    st.progress(100)
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
            embeddings,
            dimension,
            elapsed,
            knowledge_base_size,
            sparse_stats,
        ) = ingest_documents(files)

        st.session_state.knowledge_base = {
            "chunks": chunks,
            "embeddings": embeddings,
            "dimension": dimension,
            "elapsed": elapsed,
            "knowledge_base_size": knowledge_base_size,
            "sparse_stats": sparse_stats,
        }

        st.session_state.last_upload_signature = upload_signature

if st.session_state.knowledge_base:

    kb = st.session_state.knowledge_base

    chunks = kb["chunks"]
    embeddings = kb["embeddings"]
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

available_documents = MetadataCatalog.list_documents()

selected_documents = st.multiselect(
    "Limit retrieval to specific documents",
    options=available_documents,
    default=available_documents,
    format_func=lambda document: document["display_name"],
)

filters = {
    "document_ids": [
        document["document_id"]
        for document in selected_documents
    ]
}

# --------------------------------------------------
# Question Answering Section
# --------------------------------------------------
st.subheader("💬 Ask Questions")

question = st.text_input(
    "Ask something about your uploaded documents"
)

if st.button("Ask", type="primary"):

    # Returns immediately with a handle. No model call has happened yet - generation
    # starts when st.write_stream below begins pulling from handle.tokens.
    stream = ask_stream(question, filters)

    st.markdown("#### 💡 Answer")

    # write_stream renders whatever the generator yields and blocks until it is
    # exhausted. typewriter() sits between the two purely to smooth the cadence - it
    # changes nothing about the text, the order, or the sanitizing already applied.
    # The answer is no longer inside an expander: collapsing a region that is actively
    # being written to defeats the point of streaming.
    st.write_stream(typewriter(stream.tokens))

    # Only readable AFTER the stream is consumed - that is when _stream_tokens
    # assembles it. If a guardrail rejected before generation, the loop above
    # rendered nothing and this was already populated.
    response = stream.response

    # Note the ordering consequence of streaming: an output validator can only reject
    # here, once the text is already on screen. The error appears BELOW an answer the
    # user has read. That is the honest cost of streaming, not a bug to paper over.
    if not response.success:
        st.error(response.message)
        st.stop()

    st.success("✅ Answer Generated using Hybrid Retrieval (Dense + BM25 + RRF) with Verified Citations")

    # Rendered after the stream because [n] can only be resolved to a filename once
    # the full set of markers is known.
    if response.sources:
        st.caption("**Sources**")
        for source in response.sources:
            st.caption(f"`[{source.label}]` {source.display_name}")

    token_col1, token_col2 = st.columns(2)

    with token_col1:
        st.metric(
            "Prompt Tokens",
            response.token_usage.get("input_tokens", "-")
        )

    with token_col2:
        st.metric(
            "Completion Tokens",
            response.token_usage.get("output_tokens", "-")
        )

    with st.expander("⚡ Generation Details"):

        st.write("**Finish Reason**")
        st.code(response.finish_reason)

        st.write("**Latency**")
        st.code(f"{response.latency / 1_000_000:.2f} ms")

    with st.expander("📚 Retrieved Chunks"):

        st.info(f"Retrieved **{len(response.sources)}** fused chunks using Reciprocal Rank Fusion (RRF).")

        for rank, source in enumerate(response.sources, start=1):

            document = source.document

            st.markdown(f"### `[{source.label}]` — {source.display_name}")
            st.caption(f"Fusion Rank #{rank}")

            st.write(document.page_content)

            metadata_col1, metadata_col2 = st.columns(2)

            with metadata_col1:
                st.write("**Document ID**")
                st.code(document.metadata.get("document_id", "-"))

                st.write("**Chunk Index**")
                st.code(document.metadata.get("chunk_index", "-"))

            with metadata_col2:
                st.write("**Chunk ID**")
                st.code(source.chunk_id or "-")

    with st.expander("🧠 Response Metadata"):
        st.json(response.metadata)

st.divider()
# --------------------------------------------------
# Current Milestone
# --------------------------------------------------
st.subheader("📈 Current Milestone")

st.write("**Week 3 • LCEL Refactor — Complete**")

st.success(
    """
    ✅ LCEL Composition (RunnableParallel | Prompt | LLM)

    ✅ System / Human Prompt Separation

    ✅ Framework-Independent Business Layer

    ✅ Labelled Source Context

    ✅ Inline Citations

    ✅ Deterministic Citation Verification

    🚀 Next Milestone: Week 4 — Production Readiness
    """
)

st.divider()

# --------------------------------------------------
# Footer
# --------------------------------------------------
st.caption("Built in Public ❤️ | Week 3 | LCEL Refactor & Citations")