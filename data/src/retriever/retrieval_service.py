from langchain_core.documents import Document
from data.src.retriever.vector_store_retrieval import DenseRetriever
from data.src.retriever.sparse_store_retrieval import SparseRetriever
from data.src.retriever.fusion_service import Fuser

class RetrievalService:

    @staticmethod
    def retrieve(query: str, top_k: int) -> list[Document]:
        dense_store_docs = DenseRetriever.retrieve(query, top_k)
        sparse_store_docs = SparseRetriever.retrieve(query, top_k)
        fused = Fuser.fuse(dense_store_docs, sparse_store_docs)
        return fused[:3]