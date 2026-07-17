from data.src.services.document_loader_service import load_documents

def ingest_documents(uploaded_files):
    documents = load_documents(uploaded_files)
    return documents