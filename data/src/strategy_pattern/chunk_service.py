from data.src.strategy_pattern.strategy_factory import StrategyFactory

def chunk_documents(documents):
    if not documents:
        return []

    chunks = []

    for document in documents:
        strategy = StrategyFactory.create(document)
        chunks.extend(strategy.chunk(document))

    return chunks