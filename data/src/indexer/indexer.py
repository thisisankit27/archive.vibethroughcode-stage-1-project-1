from pathlib import Path
from data.src.storage.embeddings import EmbeddingService
from data.src.storage.vector_store import VectorStore

#similarly import service for constructing sparse matrix
from data.src.storage.bm25indexing import BM25Indexer

vector_store = VectorStore()
sparse_index = BM25Indexer()

DENSE_INDEX_PATH = Path("./storage/my_index.index")
SPARSE_INDEX_PATH = Path("./storage/my_sparseindex.index")
DOCUMENTS_PATH = Path("./storage/documents.pkl")

class IndexerService:

    @classmethod
    def index(self, chunks):
        embeddings, dimension, elapsed = EmbeddingService.generate_embeddings(chunks)

        # The vectors are CONSUMED here. From this line on, the FAISS index on disk is
        # the embeddings - in a form built for searching. Returning the raw list as well
        # was a leftover from PR-4, when the UI showed embedding stats and persistence
        # did not exist yet. Nothing has read it since PR-5.
        vector_store.store(chunks, embeddings)

        knowledge_base_size = vector_store.document_count()

        # similarly index and store sparse form of chunks
        sparse_stats = sparse_index.index(chunks)
        # should have a way to mark which chunk has what types of indexes (dense or dense+sparse)
        # this will help during retrieval

        return (
            dimension,
            elapsed,
            knowledge_base_size,
            sparse_stats,
        )