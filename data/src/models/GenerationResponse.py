from dataclasses import dataclass
from langchain_core.documents import Document

@dataclass
class GenerationResponse:

    success: bool

    answer: str | None = None

    metadata: dict | None = None
    token_usage: dict | None = None
    finish_reason: str | None = None
    latency: float | None = None
    documents: list[Document] | None = None

    reason: str | None = None
    message: str | None = None