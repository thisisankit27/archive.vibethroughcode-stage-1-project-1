from dataclasses import dataclass

from data.src.models.CitedSource import CitedSource


@dataclass
class GenerationResponse:

    success: bool

    answer: str | None = None

    metadata: dict | None = None
    token_usage: dict | None = None
    finish_reason: str | None = None
    latency: float | None = None
    sources: list[CitedSource] | None = None

    reason: str | None = None
    message: str | None = None
