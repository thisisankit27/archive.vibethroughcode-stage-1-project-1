import streamlit as st
from data.src.ingestion import ingest_documents
from data.src.metadata.metadata_catalog import MetadataCatalog
from data.src.rag import ask

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

    st.success("✅ PR-7 Hybrid Retrieval")

    st.info("🔜 PR-8 Metadata Filtering")
    st.info("🔜 PR-9 Guardrails")

    st.divider()

    st.subheader("Week 2 Progress")
    st.progress(33)
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

    response = ask(question, filters)

    if not response.success:
        st.error(response.message)
        st.stop()

    st.success("✅ Answer Generated using Hybrid Retrieval (Dense + BM25 + RRF)")

    with st.expander("💡 Answer", expanded=True):
        st.write(response.answer)

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

        st.info(f"Retrieved **{len(response.documents)}** fused chunks using Reciprocal Rank Fusion (RRF).")

        for rank, document in enumerate(response.documents, start=1):

            st.markdown(f"### Fusion Rank #{rank}")

            st.write(document.page_content)

            metadata_col1, metadata_col2 = st.columns(2)

            with metadata_col1:
                st.write("**Document ID**")
                st.code(document.metadata.get("document_id", "-"))

                st.write("**Chunk Index**")
                st.code(document.metadata.get("chunk_index", "-"))

            with metadata_col2:
                st.write("**Chunk ID**")
                st.code(document.metadata.get("chunk_id", "-"))

    with st.expander("🧠 Response Metadata"):
        st.json(response.metadata)

st.divider()
# --------------------------------------------------
# Current Milestone
# --------------------------------------------------
st.subheader("📈 Current Milestone")

st.write("**Week 2 • PR-7 Hybrid Retrieval**")

st.success(
    """
    ✅ Dense Retrieval (FAISS)

    ✅ Sparse Retrieval (BM25)

    ✅ Reciprocal Rank Fusion (RRF)

    ✅ Hybrid Search Pipeline

    ✅ Chunk Identity (Document ID + Chunk ID)

    ✅ Layered Retrieval Architecture

    ✅ Retrieval Strategy Abstraction

    🚀 Next Milestone: Metadata Filtering
    """
)

st.divider()

# --------------------------------------------------
# Footer
# --------------------------------------------------
st.caption("Built in Public ❤️ | Week 2 | PR-7 Hybrid Retrieval")