from dataclasses import dataclass
from langchain_core.documents import Document

@dataclass
class GenerationResponse:

    answer: str
    metadata: dict
    token_usage: dict
    finish_reason: str
    latency: float
    documents: list[Document]