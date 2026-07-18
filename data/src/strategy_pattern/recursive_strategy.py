from data.src.strategy_pattern.strategy import Strategy

from langchain_text_splitters import RecursiveCharacterTextSplitter

class RecursiveChunkStrategy(Strategy):
    def chunk(self, document):
        text_splitter = RecursiveCharacterTextSplitter(
            chunk_size = 600,
            chunk_overlap=300,
            length_function=len,
        )
        return text_splitter.split_documents([document])