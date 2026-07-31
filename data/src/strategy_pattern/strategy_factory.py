from pathlib import Path

from data.src.strategy_pattern.strategy import Strategy
from data.src.strategy_pattern.recursive_strategy import (
    RecursiveChunkStrategy,
)

# Future imports
# from python_strategy import PythonChunkStrategy
# from markdown_strategy import MarkdownChunkStrategy


class StrategyFactory:
    """
    Factory + Flyweight
    Creates strategy objects only once and reuses them.
    """

    _recursive_strategy = RecursiveChunkStrategy()

    # Future
    # _python_strategy = PythonChunkStrategy()
    # _markdown_strategy = MarkdownChunkStrategy()

    @classmethod
    def create(cls, document) -> Strategy:
        extension = Path(document.metadata["source"]).suffix.lower()

        if extension == ".pdf":
            return cls._recursive_strategy
        if extension == ".md":
            return cls._recursive_strategy
        
        # if extension == ".py":
        #     return cls._python_strategy

        raise ValueError(f"Unsupported file type: {extension}")