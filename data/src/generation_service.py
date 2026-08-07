from operator import itemgetter

from langchain_core.documents import Document
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import RunnableLambda, RunnableParallel
from langchain_ollama import ChatOllama

from data.src.models.CitedSource import CitedSource
from data.src.models.GenerationResponse import GenerationResponse
from data.src.prompts import HUMAN_PROMPT, SYSTEM_PROMPT


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
        model="llama3.2:latest"
    )

    _prompt = ChatPromptTemplate.from_messages([
        ("system", SYSTEM_PROMPT),
        ("human", HUMAN_PROMPT),
    ])

    _chain = (
        RunnableParallel(
            context=itemgetter("sources") | RunnableLambda(_render_sources),
            user_query=itemgetter("user_query"),
        )
        | _prompt
        | _llm
    )

    @classmethod
    def generate_answer(cls, user_query, retrieved_documents) -> GenerationResponse:

        sources = _label_sources(retrieved_documents)

        llm_response = cls._chain.invoke({
            "sources": sources,
            "user_query": user_query,
        })

        return GenerationResponse(
            success=True,
            answer=llm_response.content,
            metadata=llm_response.response_metadata,
            token_usage=llm_response.usage_metadata,
            finish_reason=llm_response.response_metadata.get("done_reason"),
            latency=llm_response.response_metadata.get("total_duration"),
            sources=sources,
        )
