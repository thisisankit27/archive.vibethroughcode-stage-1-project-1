from langchain_ollama import ChatOllama
from data.src.models.GenerationResponse import GenerationResponse

class GenerationService:
    _llm = ChatOllama(
        model="llama3.2:latest"
    )

    _prompt_template = """
        You are a factual assistant. Your task is to answer the user's question using ONLY the provided search results.

        <context>
        {context}
        </context>

        <rules>
        1. Base your answer strictly on the facts inside the <context> tags.
        2. If the context does not contain the answer, reply exactly with: "I cannot find the answer in the provided documents."
        3. Do not use any outside knowledge, assumptions, or speculation.
        4. Keep the response factual, objective, and under 3 sentences.
        </rules>

        Question: {user_query}
        Answer:
        """
    
    @classmethod
    def generate_answer(cls, user_query, retrieved_documents) -> GenerationResponse:
        if not retrieved_documents:
            return GenerationResponse(
                answer="I cannot find the answer in the provided documents.",
                metadata={},
                token_usage={},
                finish_reason="retrieval_failed",
                latency=0,
                documents=[],
            )
        
        formatted_prompt = cls._prompt_template.format(
            context = cls.__generate_context(retrieved_documents),
            user_query = user_query
        )
        llm_response = cls.__invoke(formatted_prompt)

        return GenerationResponse(
            answer=llm_response.content,
            metadata=llm_response.response_metadata,
            token_usage=llm_response.usage_metadata,
            finish_reason=llm_response.response_metadata.get("done_reason"),
            latency=llm_response.response_metadata.get("total_duration"),
            documents=retrieved_documents,
        )


    @classmethod
    def __generate_context(cls, retrieved_documents):
        return "\n\n".join([doc.page_content for doc in retrieved_documents])

    @classmethod
    def __invoke(cls, prompt):
        return cls._llm.invoke(prompt)