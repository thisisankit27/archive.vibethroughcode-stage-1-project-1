from data.src.strategy_pattern.strategy import Strategy

from langchain_text_splitters import RecursiveCharacterTextSplitter

from data.src.config import CHUNK_OVERLAP, CHUNK_SIZE

class RecursiveChunkStrategy(Strategy):
    def chunk(self, document):
        text_splitter = RecursiveCharacterTextSplitter(
            chunk_size=CHUNK_SIZE,
            chunk_overlap=CHUNK_OVERLAP,
            length_function=len,
        )
        return text_splitter.split_documents([document])