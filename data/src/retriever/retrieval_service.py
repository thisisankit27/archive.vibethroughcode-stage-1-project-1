from langchain_core.documents import Document

from data.src.retriever.vector_store_retrieval import DenseRetriever
from data.src.retriever.sparse_store_retrieval import SparseRetriever
from data.src.metadata.metadata_filtering import MetadataFilteringService
from data.src.retriever.fusion_service import Fuser


class RetrievalService:

    @staticmethod
    def retrieve(
        query: str,
        top_k: int,
        filters: dict,
    ) -> list[Document]:

        allowed_document_ids = set(filters.get("document_ids", []))

        dense_store_docs = DenseRetriever.retrieve(query, top_k)
        filtered_dense_docs = MetadataFilteringService.filter(
            dense_store_docs,
            allowed_document_ids,
        )

        sparse_store_docs = SparseRetriever.retrieve(query, top_k)
        filtered_sparse_docs = MetadataFilteringService.filter(
            sparse_store_docs,
            allowed_document_ids,
        )

        fused = Fuser.fuse(
            filtered_dense_docs,
            filtered_sparse_docs,
        )

        return fused[:top_k]