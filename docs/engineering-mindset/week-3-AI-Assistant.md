# Week 3 — LCEL Refactor

> Nothing new for the user.
> Everything changes internally.

Week 1 built a RAG pipeline. Week 2 made retrieval production-grade. Week 3 changes no
feature at all — it changes **how the AI layer is composed**, and asks a question that
should be asked before adopting any framework:

> What engineering problem does this actually solve, and what does it cost me?

---

## PR-10 Discussion — LCEL Composition in the Generation Layer

### Problem Statement

The generation step worked. That was the difficulty.

`GenerationService.generate_answer()` did four things in sequence, wired together by local
variables and line order:

```
1. join retrieved documents  →  one context string
2. fill the prompt template
3. call the LLM
4. map the reply             →  GenerationResponse
```

Nothing was broken. So the first honest question was whether this PR should exist at all.

It should, and the reason is not "LCEL is the modern way." It is a specific, nameable
weakness. Imagine four requirements arriving over the next two weeks:

| Requirement | What I would have to do |
| --- | --- |
| Stream tokens to the UI | Edit `generate_answer` |
| Batch 50 questions to evaluate retrieval | Edit `generate_answer` |
| Retry when Ollama times out | Edit `generate_answer` |
| Log how long each step took | Edit `generate_answer` |

One method, modified four times, for four unrelated reasons.

That is an **Open/Closed Principle** violation. The method is not closed to modification
when *execution* requirements change. Every new execution concern reaches into
orchestration code that has nothing to do with it.

> **The engineering problem is not "my code is ugly."**
> It is: *execution concerns and orchestration logic are fused in one method.*

---

### Core Thoughts — What I Believed Going In

My starting position was roughly: *LCEL is LangChain's newer syntax, so Week 3 replaces my
code with the pipe operator.*

That framing is wrong in a way worth recording, because it is the framing an interviewer
will probe. Rewriting working code in a newer syntax is a **lateral refactor** — same
behaviour, same weaknesses, new imports. It is indistinguishable from cargo-culting.

The correct framing only appeared after asking what LCEL's *bet* is:

> Make every step implement **one interface**.
> Then execution modes belong to the **composition**, not to each step.

Once `prompt`, `llm`, and the document formatter all satisfy the `Runnable` contract,
`.stream()`, `.batch()`, `.ainvoke()`, `.with_retry()` apply to the **entire chain** —
because a chain of Runnables is itself a Runnable. All four rows of the table above are
solved without touching orchestration code.

That is a real engineering argument. "It's the modern way" is not.

---

### The Roadmap Divergence — A Discovery, Not a Defect

`PR-Journey.md` describes PR-10 as:

```
Replace create_retrieval_chain(...)   with   Retriever → Prompt → LLM → Parser
```

I never built `create_retrieval_chain`. Weeks 1 and 2 hand-built the orchestration, and
`RetrievalService` already owns dense retrieval, sparse retrieval, metadata filtering, and
reciprocal rank fusion as a proper layer.

The roadmap was written **before the code existed**. The right conclusion is not "the plan
was wrong" — it is:

> I arrived at this checkpoint and found the architecture was already ahead of the plan.

So the real PR-10 is **`Prompt → LLM`**, scoped to `GenerationService`. Retrieval stays
exactly where it is.

**Interview value:** *"I evaluated the framework's helper chain and found my own retrieval
layer was already cleaner, so I adopted LCEL only where it earned its place"* is a stronger
answer than *"I used the recommended helper."*

---

### Design Decision #1 — LCEL Is the AI Composition Layer, Not the Architecture

The most consequential decision was a **boundary**, made before any code.

```
ask()
  │
  ▼ Input Guardrails         ← plain Python
  │
  ▼ RetrievalService         ← plain Python
  │
  ▼ Context Guardrails       ← plain Python
  │
  ▼ LCEL Chain               ← the ONLY framework-composed region
  │
  ▼ Output Guardrails        ← plain Python
  │
  ▼ GenerationResponse
```

**Bad version:** everything becomes a Runnable.
**Chosen version:** business logic stays plain Python; only AI composition is declarative.

**Why.** Guardrails are *business policy*. `validate_input()` is a pure function over a
string — testable with a plain `assert` and zero framework imports. Wrapping it in a
`RunnableLambda` would buy nothing and would couple domain policy to LangChain's execution
model, making the policy untestable without the framework.

Ingestion was excluded for a different reason: LCEL's value is composing **stateless
transformations**. Ingestion writes to indexes and registers metadata — side effects at
every step. Declarative composition over side-effecting steps is a lie you tell yourself.

> **Engineering Principle**
> A framework may own *composition*. It must not own *policy*.

---

### Design Decision #2 — Where the Chain Terminates

The textbook LCEL chain ends `... | llm | StrOutputParser()`. I deliberately stopped at the
LLM.

`StrOutputParser` returns `message.content` — a plain string. It **discards**
`response_metadata` and `usage_metadata`. The UI renders prompt tokens, completion tokens,
finish reason, and latency from exactly those fields.

The textbook chain would have silently broken the observability I built in Week 1.

There is a second, better reason. `GenerationResponse` is **my** type. The moment a
LangChain chain produces it, my domain object is entangled with the framework's execution
model. Keeping the mapping in the service means the chain returns something
LangChain-native and the service **translates at the boundary** — the same instinct that
stops a Spring controller returning JPA entities straight to the client.

> **Engineering Principle**
> Translate framework types into domain types at the boundary you own.

**Consequence accepted:** this chain cannot be dropped into a generic LCEL pipeline that
expects a string. That is fine — it is not a reusable public chain, it is the internal
composition of one service.

---

### Design Decision #3 — Document Formatting Lives *Inside* the Chain

Two options:

**(a)** Join documents outside the chain; pass a finished context string in.
**(b)** Join documents inside the chain; the chain accepts raw `Document` objects.

Chose **(b)**.

Under (a), the caller must know how to format context before it can use the chain — the
chain leaks its input requirements upward. Under (b) the chain is one complete unit, from
domain objects to LLM reply.

The payoff is deferred but real: when streaming arrives in Week 4, the whole transformation
is a single `.stream()` call on one object. Under (a), the caller's pre-formatting step
sits outside anything the framework can stream, batch, or trace.

> **Engineering Principle**
> A component should accept the data its caller naturally has, not a shape the caller must
> learn to construct.

---

### Design Decision #4 — RunnableParallel for **Shape**, Not Speed

This one I arrived at by hitting a wall.

The pipe operator is a straight line: whatever one step returns is *all* the next step
receives. But the prompt needs **two** variables:

```
{context}      ← derived from the documents
{user_query}   ← comes from the caller
```

So piping documents into a formatter destroys `user_query`. **A Runnable accepts exactly
one input.** That constraint is precisely *why* `RunnableParallel` exists — it is how you
carry multiple values through a single-input pipeline.

```
{"documents": [...], "user_query": "..."}       ← chain input
                │
    ┌───────────┴───────────┐        both branches receive the FULL dict
    ▼                       ▼
pluck "documents"      pluck "user_query"
    │                       │
join into one string    (unchanged)
    ▼                       ▼
{"context": "...", "user_query": "..."}         ← what the prompt needs
```

**The correction that mattered.** My first instinct — and my mentor's first framing — was
that `RunnableParallel` is about *concurrency*, and that this project had no use for it
because joining three strings is instant. That judged it on latency alone.

The real reason to reach for it here is **structural**: fanning one input out into a named
dictionary. Concurrency is a *consequence* the runtime is free to exploit; it is not the
motivation.

> **Interview answer**
> "RunnableParallel isn't primarily about concurrency. It's a declarative fan-out of one
> input into a named structure. The runtime may execute branches concurrently, but that's a
> consequence, not the reason you use it."

---

### Design Decision #5 — Split the Prompt by Ownership

Before, one string carried persona, rules, delimiters, context, and question — and it was
sent to the model as a **single human message**, because passing a plain string to
`ChatOllama.invoke()` wraps everything as one `HumanMessage`.

There was no system message at all. Carefully written rules were sitting in the user's
turn — the least authoritative position in the conversation, and the same place untrusted
input lives.

The split is by **reason to change**:

| | Changes when | Contains |
| --- | --- | --- |
| `_SYSTEM_PROMPT` | *policy* changes | persona + the four rules — developer-controlled |
| `_HUMAN_PROMPT` | *every request* | retrieved context + the question — untrusted data |

Different change frequencies, different reasons to change, therefore different places. That
is the **Single Responsibility Principle applied to a prompt**.

Retrieved context stays in the human message on purpose. It came from user-uploaded
documents, so it is **data, not instruction** — and the `<context>` delimiters mark it as
quoted material rather than commands.

Both prompts live at **module level**, not inside the class body. A triple-quoted string
keeps every character between the quotes, including indentation — written inside a class,
every line ships to the model with eight leading spaces.

---

### Design Decision #6 — `_format_documents` Is a Function, Not a Method

The document joiner was originally a `@classmethod`. Referencing it while building the
chain as a class attribute produced a `NameError`, and the fix turned out to be a design
lesson rather than a workaround.

```python
@classmethod
def __generate_context(cls, retrieved_documents):
    return "\n\n".join([doc.page_content for doc in retrieved_documents])
```

**It never uses `cls`.** Not once. It is a pure function `list[Document] → str` that was
put in a class out of habit.

> **Engineering Principle**
> If a method doesn't use `self` or `cls`, it isn't a method.

Moving it to module level fixed the ordering problem, removed the `cls` problem, and made
it unit-testable without instantiating or importing `GenerationService` at all.

This also protects **framework independence**: `_format_documents` knows nothing about
LangChain. `RunnableLambda` adapts it to the `Runnable` contract from the outside — the
**Adapter Pattern**. LangChain bends to my function; my function does not bend to
LangChain.

---

### Responsibilities — Before and After

**Before — `generate_answer()` owned:**

- joining documents into a context string
- filling the prompt template
- invoking the LLM
- mapping the reply to `GenerationResponse`
- *implicitly:* the execution strategy (sync, once, no retry, no streaming)

**After:**

| Component | Owns | Explicitly does NOT own |
| --- | --- | --- |
| `_format_documents` | turning `list[Document]` into one string | prompts, LLMs, framework types |
| `_SYSTEM_PROMPT` | answering policy and rules | per-request data |
| `_HUMAN_PROMPT` | per-request framing of context + question | policy |
| `_chain` | composition and execution strategy | domain types, business policy |
| `generate_answer` | translating the LLM reply into `GenerationResponse` | prompt construction, invocation mechanics |

The fifth bullet is the one that moved. **Execution strategy is now owned by the chain**,
which is the entire point of the PR.

---

### Final Architecture

```
RetrievalService
        │
        │  list[Document]
        ▼
GenerationService.generate_answer(user_query, retrieved_documents)
        │
        │  {"documents": [...], "user_query": "..."}
        ▼
┌───────────────────────────────────────────────┐
│                 _chain                        │
│                                               │
│   RunnableParallel                            │
│      ├── context     ← itemgetter("documents")│
│      │                 | _format_documents    │
│      └── user_query  ← itemgetter("user_query")│
│                    │                          │
│                    ▼                          │
│           ChatPromptTemplate                  │
│              system: rules                    │
│              human:  <context> + question     │
│                    │                          │
│                    ▼                          │
│                ChatOllama                     │
└───────────────────────────────────────────────┘
        │
        │  AIMessage (content + response_metadata + usage_metadata)
        ▼
GenerationResponse   ← translated in the service, not in the chain
```

---

### Mistakes I Made

The wrong attempts taught more than the final code. Recording them, because each maps to a
misconception an interviewer can expose in one question.

#### Mistake 1 — Planning to call `format_messages()` inside an LCEL chain

I said, in one breath, that I would use `format_messages()` *and* that the prompt would be
part of the LCEL pipeline. Those are opposites.

```python
# imperative — I call it, I hold the result, I pass it on
messages = prompt.format_messages(context=..., user_query=...)
response = llm.invoke(messages)

# declarative — I never call it; I wire it, and the runtime calls it
chain = prompt | llm
response = chain.invoke({"context": ..., "user_query": ...})
```

Calling `format_messages()` would have been my *existing* code with a different method
name — a cosmetic refactor.

> **Lesson:** In LCEL you do not call the prompt. You connect it. `format_messages()` is a
> debugging escape hatch, not how a chain runs.

#### Mistake 2 — Composing the chain and never invoking it

```python
llm_response = input | cls._prompt | cls._llm   # this is a RunnableSequence OBJECT
...
answer = llm_response.content                   # AttributeError
```

The exact mirror of Mistake 1. First I wanted to call everything and compose nothing; then
I composed everything and called nothing.

> **Lesson:** Composition and execution are two separate steps. `|` builds the pipeline.
> `.invoke()` runs it.

#### Mistake 3 — Putting retrieved context in an `ai` message

```python
("ai", "{context}"),
("human", "{user_input}")
```

An `ai` message means *"the assistant said this earlier."* This tells the model it
**already produced** the retrieved documents, so it treats them as its own prior output —
its own memory — rather than as evidence it must be constrained by.

> **Lesson:** Retrieved context is data. Data belongs in the human turn, inside delimiters
> that mark it as quoted material.

#### Mistake 4 — Passing two dictionaries to `.invoke()`

```python
cls._chain.invoke(
    {"context": retrieved_documents},
    {"user_input": user_query},        # silently treated as CONFIG
)
```

`invoke()`'s signature is `invoke(input, config=None)`. The second positional argument is
`RunnableConfig` — callbacks, tags, timeouts. My query was handed to LangChain as
configuration and discarded.

> **Lesson:** A Runnable takes exactly one input. This constraint is *why* `RunnableParallel`
> has to exist.

#### Mistake 5 — Referencing a classmethod from the class body

```python
class GenerationService:
    input = RunnableParallel(
        context=__generate_context(),   # NameError
    )
    ...
    @classmethod
    def __generate_context(cls, ...):   # defined 44 lines later
```

Three problems stacked: (1) a class body executes top-to-bottom *immediately*, so the name
does not exist yet; (2) `cls` does not exist until a method is called; (3) `()` calls the
function instead of passing it — LCEL needs the function object, not its return value.

> **Lesson:** A Python class body is executable code, not a declaration block. And see
> Design Decision #6 — this was Python pointing at a design problem, not a language
> limitation.

#### Mistake 6 — Every branch receives the *whole* input

```python
RunnableParallel(
    context=_format_documents,           # receives the ENTIRE dict, not documents
    user_query=RunnablePassthrough(),    # forwards the ENTIRE dict
)
```

Branches of a `RunnableParallel` are each handed the complete input. Each branch must pluck
its own key — that is what `itemgetter` is for.

`RunnablePassthrough` was the wrong tool: it forwards *everything*, and I only wanted one
key. It belongs where you genuinely want the whole input carried forward.

---

### Rejected Alternatives

| Alternative | Why rejected |
| --- | --- |
| `... \| llm \| StrOutputParser()` | Discards `usage_metadata` and `response_metadata`; silently breaks token/latency reporting |
| A custom Runnable emitting `GenerationResponse` | Drags my domain DTO into the framework's execution model |
| Guardrails as `RunnableLambda`s | Couples business policy to LangChain; destroys framework-free testability |
| `RetrievalService` inside the chain | Retrieval is the Information Expert for its own strategy; LCEL adds nothing |
| `RunnablePassthrough.assign(context=...)` | Fewer lines, but also forwards `documents`, which the prompt silently ignores. `RunnableParallel` states *exactly* what the prompt receives — explicit beats implicit at a boundary |
| Formatting documents outside the chain | Caller would need to know how to build context; breaks the chain as a self-contained unit |
| Refactoring the ingestion pipeline to LCEL | Ingestion is side-effect-heavy; LCEL composes stateless transformations |

---

### What This PR Deliberately Did *Not* Change

Restraint is a design decision and deserves to be recorded.

- `rag.py` — untouched. Orchestration order is unchanged.
- `app.py` — untouched. Zero user-visible change, as the roadmap intended.
- `RetrievalService` and everything under it — untouched.
- All three guardrail modules — untouched.
- The ingestion pipeline — untouched.
- **The prompt's wording** — rules moved verbatim. Rule 4 ("under 3 sentences") was a
  testing constraint and *should* be revisited, but changing prompt **content** is PR-11's
  responsibility. Moving text and rewriting text are two different concerns; bundling them
  would make the diff unreviewable.

> **Engineering Principle**
> One responsibility per PR applies to refactors too. A diff that both moves and rewrites
> a thing cannot be reviewed for either.

---

### Production Failure Modes

The most dangerous bug in this PR never raised an exception.

An intermediate version computed `context` correctly and then used a prompt that declared
only `{user_input}`. Extra keys are **silently ignored**. The application would have run
normally and returned confident, fluent answers built on **no retrieved context at all**.

> A crash is fixed in ten minutes. A silent quality regression ships, and you learn about it
> weeks later when someone says "the answers got worse."

Other failure modes now understood:

- **Ollama unreachable** — the chain raises; `ask()` has no `try/except` and the Streamlit
  page will show a traceback. Deliberately left for Week 4 (PR-15, Error Handling), noted
  rather than silently ignored.
- **Empty document list** — `_format_documents([])` returns `""`, producing an empty
  `<context>` block. Rule 2 should make the model refuse, but this depends on prompt
  compliance rather than a hard guarantee. `validate_context()` catches the empty case
  before generation, so the guardrail — not the prompt — is the real protection.
- **Prompt-template brace collision** — `ChatPromptTemplate` treats `{...}` as a variable
  slot. Braces inside prompt *text* would break template parsing. (Retrieved content is
  injected as a *value* and is not re-parsed, so document text is safe.)

---

### Engineering Lessons

1. **Adopt a framework for a named problem, not for its popularity.** The problem here was
   an Open/Closed violation in `generate_answer`, not "my syntax is old."
2. **A framework may own composition. It must not own policy.**
3. **Composition and execution are separate steps.** `|` wires; `.invoke()` runs.
4. **A Runnable takes exactly one input.** Every multi-value design follows from that
   constraint.
5. **If a method doesn't use `self` or `cls`, it isn't a method.**
6. **Translate framework types into domain types at the boundary you own.**
7. **Silent correctness bugs are worse than crashes.** Prefer designs that fail loudly.
8. **Split by reason to change** — including prompts. That is SRP, not formatting taste.
9. **The wrong attempt is the lesson.** Mistakes 1 and 2 are exact opposites, and holding
   both is what actually teaches the composition model.
10. **A roadmap is a learning sequence, not a spec.** Finding the code ahead of the plan is
    an outcome, not an error.

---

### Interview Takeaways

**Why LCEL instead of calling the model yourself?**

> I hand-built the imperative version first and it worked. The problem was Open/Closed:
> every new *execution* concern — streaming, batching, retries, tracing — meant editing the
> same orchestration method for an unrelated reason. LCEL makes every step implement one
> interface, so execution modes belong to the composition rather than to each step. Because
> a chain of Runnables is itself a Runnable, `.stream()` and `.batch()` apply to the whole
> pipeline for free.

**What is a Runnable, and why not a plain Python callable?**

> A callable standardizes one thing: calling it once, synchronously. `Runnable` standardizes
> `invoke`, `batch`, `stream`, their async forms, composition via `|`, plus retries,
> fallbacks, and tracing. That larger contract is what lets capabilities be added by
> composition instead of by editing each step.

**What is `RunnableParallel` for?**

> A declarative fan-out of one input into a named dictionary. A Runnable accepts exactly one
> input, but my prompt needs two variables, so `RunnableParallel` builds the multi-key
> structure the prompt expects. Concurrency is a consequence the runtime may exploit, not
> the reason you reach for it.

**Why didn't you use `StrOutputParser`?**

> It returns `message.content` and discards `response_metadata` and `usage_metadata`. My UI
> reports token usage and latency from those fields. More importantly, `GenerationResponse`
> is my domain type — I translate the framework's `AIMessage` into it at the service
> boundary rather than letting a chain produce my DTO.

**Why aren't your guardrails Runnables?**

> They're business policy, not AI composition. `validate_input()` is a pure function over a
> string, testable with a plain assert and no framework imports. Making it a Runnable would
> couple domain policy to LangChain's execution model and buy nothing — the guardrails don't
> need streaming, batching, or tracing.

**Why is retrieval outside the chain?**

> `RetrievalService` is the Information Expert for retrieval — it owns the knowledge that
> dense search, sparse search, metadata filtering, and rank fusion must happen together.
> Putting it in the chain would leak that knowledge into a chain definition without buying
> anything, since the composition is internal to one service.

**Why did you split the prompt into system and human messages?**

> They change for different reasons. Rules change when policy changes; context and question
> change every request. Beyond SRP, my original code passed one string to the model, which
> LangChain wraps as a single human message — so my rules were sitting in the user's turn,
> the same place untrusted input lives. Models weight system instructions more heavily and
> resist overriding them.

---

### Self-Check

Answer these without looking. If any is shaky, the corresponding section above is the fix.

1. What is the Open/Closed violation this PR removed?
2. What does `|` do, and what does it *not* do?
3. Why can't a chain step receive two arguments?
4. What does each branch of a `RunnableParallel` receive?
5. Why is `StrOutputParser` absent from this chain?
6. Why is `_format_documents` a module function rather than a classmethod?
7. Why does retrieved context go in the human message and never the `ai` message?
8. Which is more dangerous — an `AttributeError` on the chain, or a prompt that silently
   drops `{context}`? Why?
9. What is the second positional argument to `.invoke()`?
10. Name three things this PR deliberately did not change, and why.

---

### Biggest Takeaway

> **LCEL did not make my code shorter. It moved a responsibility.**

Before, `generate_answer` owned *what the steps are* **and** *how they execute*. After, it
owns only the translation into my domain type — the chain owns execution.

The measure of this PR is not the pipe operator. It is that streaming, batching, retries,
and tracing can now be added **without editing orchestration code** — and that guardrails,
retrieval, and ingestion remained plain Python, because none of them had that problem to
begin with.

---

**Next:** PR-11 — Prompt Engineering. Central template, configurable prompts, citations,
and the overdue conversation about Rule 4.
