from operator import itemgetter

from langchain_core.documents import Document
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import RunnableLambda, RunnableParallel
from langchain_ollama import ChatOllama

from data.src.models.CitedSource import CitedSource
from data.src.models.GenerationResponse import GenerationResponse

_SYSTEM_PROMPT = """You are a factual assistant. Your task is to answer the user's question using ONLY the provided search results.

Each search result is wrapped in a <source> tag carrying an id, like <source id="1" file="notes.md">.

<rules>
1. Base your answer strictly on the facts inside the <context> tags.
2. If the context does not contain the answer, reply exactly with: "I cannot find the answer in the provided documents."
3. Do not use any outside knowledge, assumptions, or speculation.
4. Keep the response factual, objective, and under 3 sentences.
5. Cite your sources. Immediately after each sentence, add the id of every source you used for it, in square brackets: [1]. If a sentence draws on more than one source, cite each of them: [1][3].
6. Only cite ids that appear in the <source> tags above. Never invent an id.
</rules>"""

_HUMAN_PROMPT = """<context>
{context}
</context>

Question: {user_query}"""


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
        ("system", _SYSTEM_PROMPT),
        ("human", _HUMAN_PROMPT),
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
