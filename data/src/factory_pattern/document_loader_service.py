import uuid
from data.src.factory_pattern.loader_factory import LoaderFactory

def load_documents(uploaded_files):

    if not uploaded_files:
        return []

    documents = []

    for uploaded_file in uploaded_files:
        loader = LoaderFactory.create(uploaded_file)
        loaded_document = loader.load()
        document_id = str(uuid.uuid4())
        for document in loaded_document:
            document.metadata["document_id"] = document_id
            document.metadata["display_name"] = uploaded_file.name

        documents.extend(loaded_document)

    return documents