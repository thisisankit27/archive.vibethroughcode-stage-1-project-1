from data.src.strategy_pattern.strategy_factory import StrategyFactory

def chunk_documents(documents):
    if not documents:
        return []

    chunks = []

    for document in documents:
        strategy = StrategyFactory.create(document)
        chunked_document = strategy.chunk(document)
        for chunk_index, chunk in enumerate(chunked_document):
            document_id = chunk.metadata.get("document_id")

            chunk.metadata["chunk_index"] = chunk_index
            chunk.metadata["chunk_id"] = f"{document_id}::{chunk_index}"
        chunks.extend(chunked_document)

    return chunks