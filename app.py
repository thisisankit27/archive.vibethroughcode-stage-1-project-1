import streamlit as st
from data.src.ingestion import ingest_documents
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
# Sidebar
# --------------------------------------------------
with st.sidebar:
    st.header("🗺️ Project Roadmap")

    st.success("✅ PR-1 Bootstrap")

    st.success("✅ PR-2 PDF Upload")
    st.success("✅ PR-3 Chunking")
    st.success("✅ PR-4 Embeddings")
    st.success("✅ PR-5 Vector Store")
    st.success("✅ PR-6 Basic RAG")

    st.divider()

    st.subheader("Week 1 Progress")
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

if files:

    chunks, embeddings, dimension, elapsed, knowledge_base_size = ingest_documents(files)

    st.success(
        f"Successfully indexed **{len(chunks)} chunks** into the knowledge base."
    )

    st.info(
        "✅ Your documents have been embedded and indexed. "
        "You can now ask questions in the section below."
    )

    col1, col2, col3 = st.columns(3)

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
# Question Answering Section
# --------------------------------------------------
st.subheader("💬 Ask Questions")

question = st.text_input(
    "Ask something about your uploaded documents"
)

if st.button("Ask", type="primary"):

    if not question.strip():
        st.warning("Please enter a question.")
        st.stop()

    response = ask(question)

    st.success("Answer Generated")

    with st.expander("💡 Answer", expanded=True):
        st.write(response.answer)

    col1, col2 = st.columns(2)

    with col1:
        st.metric(
            "Prompt Tokens",
            response.token_usage.get("input_tokens", "-")
        )

    with col2:
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

        for index, document in enumerate(response.documents, start=1):

            st.markdown(f"### Chunk {index}")

            st.write(document.page_content)

            st.json(document.metadata)

    with st.expander("🧠 Response Metadata"):
        st.json(response.metadata)

st.divider()

# --------------------------------------------------
# Current Milestone
# --------------------------------------------------
st.subheader("📈 Current Milestone")

st.write("**Week 1 • PR-3 Chunking Engine**")

st.success(
    """
    ✅ Project bootstrapped

    ✅ Streamlit prototype completed

    ✅ Multi-document upload

    ✅ Factory Pattern (Document Loaders)

    ✅ Strategy Pattern (Chunking Engine)

    ✅ Flyweight Pattern (Reusable Strategies)

    ✅ Recursive Character Chunking

    ✅ Chunk Preview & Metadata

    ⏳ Next milestone: Embeddings & FAISS Vector Store
    """
)

st.divider()

# --------------------------------------------------
# Footer
# --------------------------------------------------
st.caption("Built in Public ❤️ | Week 1 | PR-1 Bootstrap")