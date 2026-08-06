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

---
---

## PR-11 Discussion — Citations

### Problem Statement

`PR-Journey.md` lists four features under PR-11:

```
* Central prompt template
* Configurable prompts
* Better citations
* Better formatting
```

Those are not one responsibility. They are two: **where prompt text lives** (a refactor, no
user-visible change) and **what the model returns** (a feature). Bundling them makes the diff
reviewable for neither — the same lesson PR-10 recorded under *"What This PR Deliberately Did
Not Change."*

So PR-11 was split:

| | Scope |
| --- | --- |
| **11b** | Citations — labelled context, `CitedSource`, response field, UI |
| **11c** | Citation verification in output guardrails |
| **11a** | Prompt ownership — move prompts to their own module, resolve Rule 4 *(deferred)* |

**11b was done first, not 11a.** The prompt had to change for citations anyway, and
centralising a prompt you are about to rewrite means moving it twice.

> **Engineering Principle**
> Make the change you know is coming, then tidy the house around it.

---

### The Real Problem — One Line Destroys Identity

[generation_service.py], before PR-11:

```python
return "\n\n".join(document.page_content for document in retrieved_documents)
```

Trace what the system knows about a chunk *before* it reaches that line:

- `fusion_service.py` keys the entire RRF algorithm on `doc.metadata["chunk_id"]`
- `retrieval_service.py` filters on `document_id`
- `app.py` displays `document_id`, `chunk_index`, and `chunk_id` per chunk

Two entire PRs in Week 2 built chunk identity and a metadata catalog. Then this line throws
all of it away. What the model actually received:

```
<context>
Hybrid search combines dense and sparse retrieval.

BM25 scores documents by term frequency and inverse document frequency.

The RRF constant k is typically set to 60.
</context>
```

Two consequences, and the second is worse:

1. **The model cannot cite.** Not "cites badly" — it has no handles to cite *with*. Asking
   for citations would make it invent them.
2. **The model cannot tell where one source ends and the next begins.** `\n\n` is a blank
   line, which also appears inside prose. Chunk 1 from a PDF and chunk 3 from a different
   file read as one continuous passage — so the model will synthesize a claim spanning two
   unrelated documents and present it as one fact.

> The retrieval layer preserves identity all the way to the generation boundary, and then
> the generation layer discards it.

---

### Design Decision #7 — Level 1 Citations Only

Two products hide inside the word "citations":

| | Needs | Available? |
| --- | --- | --- |
| **Level 1** — *"this claim came from `01-vision.md`, chunk 4"* | chunk metadata | ✅ already |
| **Level 2** — *"click to open the PDF at page 3"* | the original file on disk | ❌ deleted |

Both loaders write uploads to a temp file and delete it in a `finally` block, so the original
PDF or Markdown is gone after ingestion. Level 2 is therefore **not a prompt-engineering
problem** — it is a storage problem: where do uploads live, who cleans them up, what is the
size cap, and are we permitted to retain user documents at all.

**Chose Level 1.** Level 2 deferred as new scope, not as a gap.

**Latent defect found while investigating:** `metadata_catalog.json` persists
`"source": "/tmp/tmp1zu_iotv.pdf"` — a permanently dead path, because the temp file was
deleted at ingestion. Logged, not fixed here.

> Missing data makes you go and find it. **Misleading data makes you build on it.**

---

### Design Decision #8 — Free-Text Markers, Not Structured Output

Two ways to get structure out of a model:

**(a)** Free text with markers — `"...dense and sparse retrieval [1]."` — parsed afterwards.
**(b)** Structured output — `{"answer": "...", "citations": [...]}` via Pydantic/JSON.

**Chose (a)**, for two independent reasons:

1. **Streaming.** Week 4 adds token streaming. Free text streams naturally; structured output
   forces you to buffer the whole reply before it parses, destroying time-to-first-token.
2. **Model capability.** This runs `llama3.2` locally, not a frontier model. Structured output
   is a *capability, not a given* — a small model produces malformed JSON often enough to need
   retry logic, which costs more complexity than the parsing it was meant to avoid.

**A streaming consequence discovered during the discussion:** a marker does not arrive as a
marker. It arrives as `[`, then `1`, then `]` — separate tokens, possibly in separate stream
chunks. A per-token resolver sees a bare `[` and has nothing to match. **Therefore markers are
resolved after the stream completes**, not during it.

---

### Design Decision #9 — Request-Scoped Labels With a Materialized Mapping

The hardest decision of the PR. Three candidates:

| Marker | Fails because |
| --- | --- |
| **Positional** `[1] [2] [3]`, meaning *"index into `documents`"* | Meaning is **implied by list order**. Any re-sort, de-dup, or filter between generation and rendering silently attributes a claim to the wrong file. Fails silently and wrongly. |
| **`chunk_id`** `[03e94fc0-…::4]` | Order-independent and verifiable, but ~25 tokens per marker, and a 3B model cannot reliably copy a 36-character UUID. Bad copies get dropped, so the feature *works* while quietly discarding a large share of its citations. |
| **Corpus-wide document index** `[7] [412] [9004]` | Same copying-fidelity problem in milder form; uses a corpus-scoped identifier for a request-scoped need; and is per-*document*, losing chunk precision. |

The mistake in all three was collapsing two separate properties into one choice. Positional
markers were rejected for being **order-dependent**, not for being **short**.

**Chosen:** short labels (`1`, `2`, `3`) assigned at prompt-build time, with the label→chunk
pairing **stored explicitly as data** rather than inferred from position:

```python
@dataclass(frozen=True)
class CitedSource:
    label: str
    document: Document
```

| Property | How it is obtained |
| --- | --- |
| Model copies it reliably | one character, not thirty-six |
| Order cannot corrupt it | the pairing is materialized, not inferred |
| Guardrail can verify it | set membership over labels |
| Chunk-precise | one label per chunk, not per document |
| Scales to any corpus | never more than `TOP_K` labels exist |

> **Engineering Principle**
> **Scope an identifier to the scope of its use.** The marker is only ever read inside one
> prompt and one response. It never needs to be unique beyond that.

`frozen=True` makes it immutable — a request-scoped pairing nothing downstream can quietly
rewrite.

**Rejected: store the label in `chunk.metadata["label"]`.** No new type needed, and
`documents` already reached the UI. Rejected because it *mutates objects the generation layer
does not own*, and puts request-scoped data into a dict holding persistent document facts — a
`Document` retrieved for a second question would carry a stale label from the first.

---

### Design Decision #10 — Labelling Is a Business Decision, Rendering Is Formatting

The blocking question was: *"how do I get the label→chunk mapping back **out** of the chain?"*

The answer was that it never needed to go **in**. The mapping is used by the service (to build
the response) and by the UI (to render `[2]` as `01-vision.md`). Nothing inside the chain
needs it. Threading it through would force the chain to return `{answer, mapping}` — dragging
non-AI data through the AI composition layer and breaking PR-10's boundary.

So `_format_documents` split into two functions that were always two jobs:

| Function | Owns | Lives in |
| --- | --- | --- |
| `_label_sources` | assigning identity to chunks | the **service** — plain Python |
| `_render_sources` | turning labelled sources into prompt text | the **chain** — `RunnableLambda` |

```
GenerationService.generate_answer(user_query, retrieved_documents)
    │
    │  ① LABEL — a business decision, made in the service
    ▼
sources = [ CitedSource("1", chunk0),
            CitedSource("2", chunk1),
            CitedSource("3", chunk2) ]
    │
    ├──────────────────────────────────────────┐
    │  ② into the chain                        │  ④ straight into the response
    ▼                                          │
{"sources": sources, "user_query": "..."}      │
    │                                          │
    ▼   ┌──────────── _chain ──────────────┐   │
        │ RunnableParallel                 │   │
        │   context    ← _render_sources   │   │   ③ RENDER — prompt formatting,
        │   user_query ← itemgetter        │   │      stays inside the chain
        │            │                     │   │
        │            ▼                     │   │
        │      prompt | llm                │   │
        └──────────────────────────────────┘   │
    │                                          │
    ▼  AIMessage                               │
    └──────────────────┬───────────────────────┘
                       ▼
       GenerationResponse(answer=..., sources=sources, ...)
```

**One list, built once at ①, consumed at ② and ④.** There is no synchronisation problem
because there is nothing to synchronise. PR-10's Design Decision #3 survives intact — the
chain still owns formatting. It simply no longer owns *identity*.

> **Engineering Principle**
> When asked "how do I get this data out of X?", first ask whether it ever belonged in X.

---

### Design Decision #11 — Context Format Solves the Boundary Problem

```
<source id="1" file="01-vision.md">
Hybrid search combines dense and sparse retrieval.
</source>

<source id="2" file="notes.pdf">
RRF uses a constant k, typically 60.
</source>
```

Chosen over the more verbose `<label>[1]</label>:<chunk>…</chunk>` — roughly half the tokens
per chunk (two tags instead of four), and it fixes the *original* defect: the model can now
see unambiguously where one source ends and the next begins.

The filename is included deliberately. The UI does not need it there — it resolves `[1]` from
the mapping — but it helps the model reason about which source is which.

Two prompt rules were added. Rule 6 — *"only cite ids that appear in the `<source>` tags,
never invent an id"* — is the instruction that PR-11c verifies.

---

### Design Decision #12 — Sanitize, Don't Reject (PR-11c)

A model **will** cite `[4]` when only three sources exist. Small models do this regularly.
Three possible responses:

| Behaviour | Verdict |
| --- | --- |
| Reject the whole answer | Punishes the user for the model's sloppiness. The *answer* isn't wrong — one *attribution* is. |
| Leave the bad marker | Shows a citation that resolves to nothing. Actively misleading. |
| **Strip the unverifiable marker, keep the answer** | ✅ Chosen |

**How to defend it to a PM:** *a wrong source link is worse than no source link, but both are
better than no answer.*

Verification needs **no LLM at all**. It is set membership — do the markers in the answer map
to labels that were actually issued? Deterministic, instant, free, and 100% reliable.

> **Engineering Principle**
> Check what is structurally checkable with code. Reach for a model only for what genuinely
> requires judgment.
>
> Citation *existence* is code. Citation *supportiveness* — does chunk 2 actually back this
> claim — is judgment, and remains a stub.

**This forced a distinction that had been lurking since the streaming discussion:** the output
guardrails module now contains two different *kinds* of thing.

| | Contract | Signature | Can it run mid-stream? |
| --- | --- | --- | --- |
| **Validator** — `_check_empty_response`, `_check_safety` | answers yes/no, rejects | returns `GenerationResponse \| None` | ❌ needs the whole answer |
| **Sanitizer** — `_strip_unverified_citations` | repairs in place, never rejects | returns `None` | ✅ only needs a complete marker |

Naming the sanitizer `_validate_relevance` — a `validate_*` name in a module of `validate_*`
functions — would have meant a reader could not tell which contract they were getting.
`_validate_relevance` stays as the stub for the future LLM judge; stripping got its own honest
name.

> **Engineering Principle**
> Split by **contract**, not just by what the code touches. A function that repairs and a
> function that rejects do not belong under the same naming convention.

---

### Responsibilities After PR-11

| Component | Owns | Does NOT own |
| --- | --- | --- |
| `CitedSource` | the label↔chunk pairing; knowing which metadata key holds the filename | rendering, verification |
| `_label_sources` | assigning identity | prompt text, framework types |
| `_render_sources` | how labelled context looks to the model | identity |
| `GenerationService` | building sources once, using them twice | verification, display |
| `_strip_unverified_citations` | repairing invented markers | rejecting answers, judging relevance |
| `app.py` | resolving `[n]` → filename via the response | any catalog lookup |

**`MetadataCatalog` is deliberately not involved.** It answers *"what documents exist in the
corpus?"* — used by the filter multiselect. A citation asks *"what text supported **this**
answer?"* Different question, different owner, different lifetime. Routing citations through
the catalog would add a dependency and a failure mode to retrieve data already in hand.

---

### Mistakes I Made

#### Mistake 7 — Module-level mutable state for the labels

```python
_doclabel = []          # shared across every request
    _doclabel.empty()   # and cleared at the start of each one
```

Two requests in flight and request B clears the list while request A is still rendering it —
A cites documents it never retrieved. Streamlit hides this today because it is effectively
single-user. The bug is real.

It also created an invisible contract: `_format_documents` only worked if `_label_chunks` had
run first, in the right order, with nothing in between.

> **Lesson:** a global turned two pure functions into an ordering dependency. Passing the list
> as a parameter removed the global, the contract, and the concurrency bug in one change.

#### Mistake 8 — Trying to mutate a string parameter

```python
def _validate_relevance(response: str, sources):
    # erase that cite from response.answer
```

Two problems stacked: `response` was the answer *string*, which has no `.answer`; and Python
strings are **immutable**, so no function can edit one in place. The fix was already five
lines up in the same file — `_check_empty_response` mutates successfully because it receives
the whole `GenerationResponse`, and a dataclass is mutable.

> **Lesson:** whether a function can change its argument depends on the argument's **type**,
> not on how it is passed. `str`, `int`, `tuple` — immutable. `list`, `dict`, dataclasses —
> mutable.

#### Mistake 9 — Storing only `chunk_id` in the pairing

`CitedSource(label, chunk_id)` would have forced the UI to look the chunk up somewhere to find
its filename — reintroducing the lookup the design had just removed — and would have broken
the "Retrieved Chunks" panel, which needs `page_content`. Holding the `Document` and deriving
`display_name` and `chunk_id` as properties keeps metadata-key knowledge in one place instead
of scattered through `app.py`.

#### Mistake 10 — Forgetting what was already built

I proposed persisting documents in the metadata catalog. `MetadataCatalog.register()` had been
doing exactly that since PR-8.

> **Lesson:** independently re-deriving your own design is a good signal about the design and
> a bad signal about how much of the codebase you can hold in your head. This document exists
> because of that.

---

### Production Failure Modes

- **The model cites `[4]` when three sources exist.** Handled — stripped by the sanitizer.
- **The model omits citations entirely.** Not handled. The answer is still correct, just
  unattributed. Accepted: enforcing citation *presence* would mean rejecting valid answers.
- **The model cites correctly but the source doesn't support the claim.** Not handled — that
  is judgment, not structure, and needs the LLM judge still stubbed at `_validate_relevance`.
- **`llama3.2` follows citation instructions inconsistently.** Expected. This is a prompt and
  model-capability limit, not a code defect.
- **Concurrency.** All citation state is request-scoped and passed by parameter. No shared
  mutable state was introduced.

---

### Interview Takeaways

**How do you attribute an LLM's answer to its sources?**

> Retrieval already knows chunk identity, so the job is to stop throwing it away at the prompt
> boundary. I label each retrieved chunk at prompt-build time, render the labels into the
> context inside `<source>` tags, and instruct the model to cite them. The label→chunk pairing
> is stored explicitly as data, so nothing downstream can reorder its way into a wrong
> attribution.

**Why not use structured output for citations?**

> Two reasons. Streaming — free text with markers streams token by token, whereas JSON has to
> be buffered and parsed before anything can render, which destroys time-to-first-token. And
> model capability — I run a 3B local model, and reliable structured output is a capability
> not every model has. Chasing it would have meant retry logic costing more than the parsing
> it replaced.

**How do you know the citations are real?**

> Deterministically. Verifying that a cited label was actually issued is set membership — no
> model needed, instant and exact. I only reach for an LLM judge for the part that genuinely
> requires judgment: whether the cited chunk actually *supports* the claim. Structure gets
> code; semantics gets a model.

**What do you do when a citation is wrong?**

> Strip the marker, keep the answer. The answer isn't wrong — one attribution is. Rejecting
> the whole response punishes the user for the model's sloppiness, and leaving a marker that
> resolves to nothing is actively misleading. A wrong source link is worse than no source
> link, but both are better than no answer.

**Why are your markers short numbers rather than chunk IDs?**

> A marker is only ever read inside one prompt and one response, so it only needs to be unique
> within that scope. A UUID costs ~25 tokens each time it appears and a small model can't copy
> it reliably. Short labels are copyable — and because the label→chunk pairing is stored
> explicitly rather than inferred from list position, they don't inherit the fragility of
> positional references.

---

### Self-Check

1. Why can the model not cite when context is joined with `\n\n`?
2. What is the difference between Level 1 and Level 2 citations, and why is Level 2 not a
   prompt problem?
3. Why do free-text markers beat structured output *in this system specifically*?
4. Positional markers and short labels — what exactly is the difference?
5. Why does the label→chunk mapping never enter the chain?
6. Which is a validator and which is a sanitizer, and how do their signatures differ?
7. Why does citation verification need no LLM, while relevance checking does?
8. What breaks if `_label_sources` writes to a module-level list?
9. Why does `CitedSource` hold a `Document` rather than a `chunk_id`?
10. Why is `MetadataCatalog` deliberately absent from the citation path?

---

### Biggest Takeaway

> **The feature was never "make the model cite." It was "stop destroying identity at the
> prompt boundary."**

Weeks 1 and 2 built chunk identity carefully and then a single `str.join` discarded it. The
prompt rule asking for citations was the smallest part of this PR; the real work was deciding
*what identity to hand the model*, *who owns assigning it*, and *what verifies it afterwards*.

The second lesson is that an LLM feature is not finished when the model produces output. It is
finished when something deterministic has checked the part of that output which can be
checked.

---

**Week 3 complete.** Deferred deliberately: **PR-11a** — move prompts into their own module
and resolve Rule 4's 3-sentence test constraint. **Week 4** opens with streaming, where the
validator/sanitizer split above becomes load-bearing.
