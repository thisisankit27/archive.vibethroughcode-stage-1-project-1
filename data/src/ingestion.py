from data.src.factory_pattern.document_loader_service import load_documents
from data.src.strategy_pattern.chunk_service import chunk_documents

def ingest_documents(uploaded_files):
    documents = load_documents(uploaded_files)
    chunks = chunk_documents(documents)
    
    return chunks