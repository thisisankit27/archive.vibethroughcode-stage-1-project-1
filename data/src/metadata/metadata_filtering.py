from langchain_core.documents import Document

class MetadataFilteringService:

    @staticmethod
    def filter(
        documents: list[Document],
        allowed_document_ids: set[str],
    ) -> list[Document]:

        # No filters selected → search all documents
        if not allowed_document_ids:
            return documents

        filtered_documents = []

        for document in documents:
            if document.metadata["document_id"] in allowed_document_ids:
                filtered_documents.append(document)

        return filtered_documents