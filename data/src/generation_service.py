from collections.abc import Iterator
from operator import itemgetter

from langchain_core.documents import Document
from langchain_core.messages import AIMessage, AIMessageChunk
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import RunnableLambda, RunnableParallel
from langchain_ollama import ChatOllama

from data.src.config import GENERATION_MODEL, OLLAMA_BASE_URL
from data.src.models.CitedSource import CitedSource
from data.src.models.GenerationResponse import GenerationResponse
from data.src.prompts import HUMAN_PROMPT, SYSTEM_PROMPT
from data.src.resilience import call_with_retry, retryable_stream


def _label_sources(retrieved_documents: list[Document]) -> list[CitedSource]:
    return [
        CitedSource(label=str(position), document=document)
        for position, document in enumerate(retrieved_documents, start=1)
    ]


def _render_sources(sources: list[CitedSource]) -> str:
    return "\n\n".join(
        f'<source id="{source.label}" file="{source.display_name}">\n'
        f"{source.document.page_content}\n"
        f"</source>"
        for source in sources
    )


class GenerationService:
    _llm = ChatOllama(
        model=GENERATION_MODEL,
        base_url=OLLAMA_BASE_URL,
    )

    _prompt = ChatPromptTemplate.from_messages([
        ("system", SYSTEM_PROMPT),
        ("human", HUMAN_PROMPT),
    ])

    _chain = (
        RunnableParallel(
            context=itemgetter("sources") | RunnableLambda(_render_sources),
            user_query=itemgetter("user_query"),
            # PR-13: a third branch, plucked through unchanged. RunnableParallel is a
            # declarative fan-out of one input into a named structure, so carrying an
            # extra value to the prompt costs exactly one line - which is the payoff for
            # having chosen it over RunnablePassthrough.assign in PR-10.
            history=itemgetter("history"),
        )
        | _prompt
        | _llm
    )

    @classmethod
    def generate_answer(
        cls,
        user_query,
        retrieved_documents,
        history: str | None = None,
    ) -> GenerationResponse:
        """Blocking generation. Returns only when the whole answer exists."""

        sources = _label_sources(retrieved_documents)

        # Safe to retry: generation has no side effects, so a repeated attempt costs latency
        # and nothing else.
        llm_response = call_with_retry(
            "generation.invoke",
            "ollama",
            lambda: cls._chain.invoke({
                "sources": sources,
                "user_query": user_query,
                "history": history or "",
            }),
        )

        return cls.build_response(llm_response, sources)

    @classmethod
    def stream_answer(
        cls,
        user_query,
        retrieved_documents,
        history: str | None = None,
    ) -> tuple[list[CitedSource], Iterator[AIMessageChunk]]:
        """Incremental generation. Returns immediately; nothing runs until the
        iterator is consumed.

        This method is deliberately NOT a generator function. If it contained a
        `yield`, calling it would return a generator object and the caller could
        never get `sources` out of it - it would have to be smuggled through a
        mutable argument. Because `.stream()` already hands back an iterator, this
        stays a plain function and returns both values honestly.

        `sources` is built here, exactly once, and used twice: fed into the chain
        (so the prompt can render <source id="1">) and handed to the caller (so the
        UI can resolve [1] to a filename). Same one-list-two-uses design as PR-11b.

        Note what this method does NOT own: buffering, flush timing, and guardrails.
        Those are sequencing policy and belong to rag.py. This method owns only the
        execution mode - which is the responsibility PR-10 moved into the chain.
        """

        sources = _label_sources(retrieved_documents)

        # Retried ONLY until the first chunk arrives. After a token has been handed out it has
        # been painted on somebody's screen, and restarting the stream would replay it - the
        # user would watch the answer begin twice. The common failure (Ollama down) fails on
        # the first chunk anyway, which is exactly where retrying is both safe and useful.
        chunks = retryable_stream(
            "generation.stream",
            "ollama",
            lambda: cls._chain.stream({
                "sources": sources,
                "user_query": user_query,
                # Empty string, not None - an empty <history> block renders harmlessly, while
                # None would put the literal word "None" in front of the model.
                "history": history or "",
            }),
        )

        return sources, chunks

    @classmethod
    def build_response(
        cls,
        message: AIMessage | AIMessageChunk | None,
        sources: list[CitedSource],
    ) -> GenerationResponse:
        """Translate LangChain's message type into our domain type.

        Lifted out of generate_answer in PR-12a so the streaming path can reuse it.
        This is the only place in the codebase that knows an AIMessage keeps its
        finish reason at response_metadata["done_reason"] - INVARIANT #2: translate
        framework types at the boundary you own. rag.py must never touch these fields.

        `message` may be None when the model produced no chunks at all. That is not
        an error here; it becomes an empty answer, which _check_empty_response in the
        output guardrails is the correct owner of rejecting.
        """

        if message is None:
            return GenerationResponse(success=True, answer="", sources=sources)

        response_metadata = message.response_metadata or {}

        return GenerationResponse(
            success=True,
            answer=message.content,
            metadata=response_metadata,
            token_usage=message.usage_metadata,
            finish_reason=response_metadata.get("done_reason"),
            latency=response_metadata.get("total_duration"),
            sources=sources,
        )
