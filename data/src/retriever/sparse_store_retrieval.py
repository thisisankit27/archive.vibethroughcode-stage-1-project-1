from langchain_core.documents import Document
from data.src.storage.bm25indexing import BM25Indexer

_bm25_index = BM25Indexer()

class SparseRetriever:

    @classmethod
    def retrieve(cls, query: str, top_k: int) -> list[Document]:
        matched_sparse_store_docs = _bm25_index.search(query, top_k)
        return matched_sparse_store_docs
        