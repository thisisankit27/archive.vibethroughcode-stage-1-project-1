from langchain_core.documents import Document

from data.src.config import RRF_K as _RRF_K


class Fuser:
    RRF_K = _RRF_K

    @classmethod
    def fuse(cls, dense_docs: list[Document], sparse_docs: list[Document]) -> list[Document]:
        fusion_dict = {}

        # Populate dense ranks
        for rank, doc in enumerate(dense_docs, start=1):
            current_id = doc.metadata["chunk_id"]

            fusion_dict[current_id] = {
                "document": doc,
                "dense_rank": rank,
                "sparse_rank": None
            }

        # Populate sparse ranks
        for rank, doc in enumerate(sparse_docs, start=1):
            current_id = doc.metadata["chunk_id"]

            if current_id in fusion_dict:
                fusion_dict[current_id]["sparse_rank"] = rank
            else:
                fusion_dict[current_id] = {
                    "document": doc,
                    "dense_rank": None,
                    "sparse_rank": rank
                }

        # Calculate RRF score
        for entry in fusion_dict.values():
            score = 0

            if entry["dense_rank"] is not None:
                score += 1 / (cls.RRF_K + entry["dense_rank"])

            if entry["sparse_rank"] is not None:
                score += 1 / (cls.RRF_K + entry["sparse_rank"])

            entry["score"] = score

        # Sort by score (highest first)
        ranked_entries = sorted(
            fusion_dict.values(),
            key=lambda entry: entry["score"],
            reverse=True
        )

        # Return only the documents
        return [entry["document"] for entry in ranked_entries]