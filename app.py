import streamlit as st
from data.src.ingestion import ingest_documents

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
    st.write("⬜ PR-4 Embeddings")
    st.write("⬜ PR-5 Vector Store")
    st.write("⬜ PR-6 Basic RAG")

    st.divider()

    st.subheader("Week 1 Progress")
    st.progress(50)

# --------------------------------------------------
# Main Page
# --------------------------------------------------
st.title("🦈 Knowledge Assistant")
st.caption("Build your own private knowledge base using AI.")

st.divider()

# --------------------------------------------------
# Upload Section
# --------------------------------------------------
st.subheader("📄 Upload Documents")

files = st.file_uploader(
    "Upload your PDF",
    type=["pdf", "md"],
    accept_multiple_files=True,
    disabled=False
)

chunks = ingest_documents(files)

if chunks:

    st.success(f"Generated {len(chunks)} chunks.")
    selected_chunk = st.number_input(
        "Preview Chunk",
        min_value=1,
        max_value=len(chunks),
        value=1,
    )

    chunk = chunks[selected_chunk - 1]

    with st.expander("📄 Chunk Content", expanded=True):
        st.write(chunk.page_content)

    with st.expander("🏷️ Metadata"):
        st.json(chunk.metadata)

st.divider()

# --------------------------------------------------
# Question Answering Section
# --------------------------------------------------
st.subheader("💬 Ask Questions")

st.info("🚧 Question Answering will be available after **PR-6 (Basic RAG)**.")

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