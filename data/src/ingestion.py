from data.src.factory_pattern.document_loader_service import load_documents
from data.src.strategy_pattern.chunk_service import chunk_documents
from data.src.embeddings import EmbeddingService
from data.src.vector_store import VectorStore

vector_store = VectorStore()

def ingest_documents(uploaded_files):

    documents = load_documents(uploaded_files)

    chunks = chunk_documents(documents)

    embeddings, dimension, elapsed = EmbeddingService.generate_embeddings(chunks)

    vector_store.store(chunks, embeddings)

    return chunks, embeddings, dimension, elapsed