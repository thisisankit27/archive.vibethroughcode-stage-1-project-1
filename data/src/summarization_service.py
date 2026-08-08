"""Maintains the running conversation summary.

A peer of GenerationService, not a part of it. Both call an LLM; that is where the
similarity ends. This one answers "what has this conversation been about", which changes
for entirely different reasons than "how do I answer this question from these documents".

WHY THIS IS A SEPARATE CALL

An earlier design had the answer prompt emit the summary alongside the answer. Rejected:

  - it would put summary text into the token stream the user is reading, and stripping it
    mid-stream is the split-marker problem again but spanning a whole block
  - it asks a 3B model to do two unrelated jobs in one pass, and a failure in either
    corrupts the other
  - PR-11 Design Decision #8 already concluded this model is not reliable at structured
    output; that conclusion did not stop being true here

WHY IT COSTS NOTHING THE USER CAN FEEL

rag.py runs this AFTER the last token has been flushed. The summary produced now is used
by the NEXT question, so it is never on the critical path between a question and its first
token. Work moved from read time to write time - the same trade a materialized view makes.
"""

from langchain_core.prompts import ChatPromptTemplate
from langchain_ollama import ChatOllama

from data.src.config import OLLAMA_BASE_URL, SUMMARIZATION_MODEL
from data.src.observability import get_logger, log_event, stage
from data.src.prompts import SUMMARY_HUMAN_PROMPT, SUMMARY_SYSTEM_PROMPT

_logger = get_logger("summarization")


class SummarizationService:

    # A separate setting from GENERATION_MODEL even though both default to the same value.
    # Summarizing is a cheaper job than answering, so these should be free to diverge.
    _llm = ChatOllama(
        model=SUMMARIZATION_MODEL,
        base_url=OLLAMA_BASE_URL,
    )

    _prompt = ChatPromptTemplate.from_messages([
        ("system", SUMMARY_SYSTEM_PROMPT),
        ("human", SUMMARY_HUMAN_PROMPT),
    ])

    # .invoke(), not .stream(). Nobody is watching this run, so there is no
    # time-to-first-token to protect - streaming would add machinery for no reader.
    _chain = _prompt | _llm

    @classmethod
    def summarize(
        cls,
        previous_summary: str | None,
        user_query: str,
        answer: str,
    ) -> tuple[str, dict]:
        """Fold the newest exchange into the running summary.

        Returns (candidate_summary, token_usage). The caller decides whether the candidate
        is fit to keep - this service produces text, it does not police it.

        Token usage is returned rather than swallowed because this call is a real cost the
        user's conversation incurs. Reporting the answer's tokens while hiding this one
        would make the cost meter quietly understate by roughly half.
        """

        # Timed even though it is off the critical path - if this ever grows to seconds it
        # would still be felt as the page staying busy after the answer finished.
        with stage(_logger, "summarization", had_previous=bool(previous_summary)):
            message = cls._chain.invoke({
                # An empty string rather than None: the prompt template renders it into the
                # <previous_summary> block either way, and "None" would be a literal word the
                # model reads as content.
                "previous_summary": previous_summary or "",
                "user_query": user_query,
                "answer": answer,
            })

        usage = message.usage_metadata or {}

        log_event(
            _logger,
            "summarization.cost",
            input_tokens=usage.get("input_tokens"),
            output_tokens=usage.get("output_tokens"),
        )

        return message.content, usage
