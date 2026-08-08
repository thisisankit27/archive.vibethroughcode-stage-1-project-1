from data.src.factory_pattern.document_loader_service import load_documents
from data.src.metadata.metadata_catalog import MetadataCatalog
from data.src.strategy_pattern.chunk_service import chunk_documents
from data.src.storage.vector_store import VectorStore
from data.src.indexer.indexer import IndexerService

vector_store = VectorStore()

def ingest_documents(uploaded_files):

    documents = load_documents(uploaded_files)
    MetadataCatalog.register(documents)
    chunks = chunk_documents(documents)

    dimension, elapsed, knowledge_base_size, sparse_stats = IndexerService.index(chunks)

    return chunks, dimension, elapsed, knowledge_base_size, sparse_stats