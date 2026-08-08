

# Stage 1 — Knowledge Assistant v1

> Goal: Build a minimal but production-structured RAG application from scratch.

---

# WEEK 1 — Core RAG

By the end of Week 1, the application should answer questions from uploaded PDFs using semantic search.

---

## PR-1 — Project Bootstrap

### Goal

Create a clean foundation.

### Features

* Initialize project
* Virtual environment
* `requirements.txt`
* `.env.example`
* Folder structure
* Basic Streamlit UI
* GitHub README
* `.gitignore`

### Folder Structure

```text
knowledge-assistant/
│
├── app.py
├── requirements.txt
├── .env.example
├── README.md
│
├── data/
├── src/
│   ├── loaders.py
│   ├── splitter.py
│   ├── embeddings.py
│   ├── vectorstore.py
│   └── rag.py
│
└── assets/
```

### Concepts Learned

* Project architecture
* Environment management
* Modular code organization

---

## PR-2 — PDF Upload & Loading

### Goal

Users can upload one or more PDFs.

### Features

* Streamlit file uploader
* Save uploaded files
* Read PDFs using LangChain
* Display extracted text count
* Basic validation

### Concepts

* Document Loaders
* LangChain Document object
* Metadata
* File handling

Interview Topic

> Explain the LangChain `Document` class.

---

## PR-3 — Chunking Engine

### Goal

Convert documents into chunks.

### Features

* RecursiveCharacterTextSplitter
* Chunk size configuration
* Overlap configuration
* Chunk preview

### Concepts

* Chunking
* Overlap
* Recursive splitting

Interview Topics

* Why Recursive splitter?
* Why overlap?
* How do you choose chunk size?

---

## PR-4 — Embedding Pipeline

### Goal

Convert chunks into vectors.

### Features

* Initialize embedding model
* Generate embeddings
* Show embedding dimensions
* Measure embedding time

### Concepts

* Embeddings
* Vector dimensions
* Embedding models

Interview Topics

* Why embeddings?
* Why dimensions matter?
* Re-indexing

---

## PR-5 — Vector Database (FAISS)

### Goal

Store embeddings.

### Features

* Create FAISS index
* Persist locally
* Reload index
* Display document count

### Concepts

* Vector databases
* Similarity search
* Persistence

Interview Topics

* FAISS vs Chroma
* Why SQL can't do this

---

## PR-6 — Basic RAG

### Goal

Users can ask questions.

### Features

* Similarity search
* Retrieve Top-K chunks
* Pass context to LLM
* Display answer

### Concepts

* Retrieval
* Top-K
* Prompt template
* RetrievalQA

Interview Topics

* End-to-end RAG flow
* Retrieval pipeline

---

# WEEK 2 — Better Retrieval

The app should now behave more like a production search system.

---

## PR-7 — Hybrid Search

### Features

* Add BM25
* Dense + Sparse retrieval
* Compare results
* Toggle retrieval strategy

### Concepts

* Hybrid Search
* BM25
* Sparse retrieval

---

## PR-8 — Metadata Filtering

### Features

* Metadata support
* Filter by filename
* Filter by page
* Dynamic filtering groundwork

### Concepts

* Metadata
* Structured search
* Self-query preparation

---

## PR-9 — Guardrails

### Features

* Reject empty questions
* Reject prompt injection attempts
* Out-of-context detection
* Fallback responses

### Concepts

* Input guardrails
* Output guardrails
* Prompt injection

---

# WEEK 3 — LCEL Refactor

Nothing new for the user.

Everything changes internally.

---

## PR-10 — Refactor to LCEL

### Goal

Replace helper chains with explicit LCEL.

Replace

```python
create_retrieval_chain(...)
```

with

```text
Retriever

↓

Prompt

↓

LLM

↓

Parser
```

### Concepts

* Runnable
* Pipe operator
* LCEL
* Composability

Interview Topics

* Why LCEL?
* RunnableSequence
* RunnableParallel

---

## PR-11 — Prompt Engineering

Originally one PR with four features. Those features turned out to be two different
responsibilities — *what the model returns* (a feature) and *where prompt text lives* (a
refactor) — so PR-11 was split. Citations shipped first, because the prompt had to change for
them anyway and centralising a prompt you are about to rewrite means moving it twice.

| | Scope | Status |
| --- | --- | --- |
| **11b** | Citations — labelled `<source>` context, `CitedSource`, response field, UI | ✅ shipped |
| **11c** | Deterministic citation verification in output guardrails | ✅ shipped |
| **11a** | Prompt ownership — prompts get their own module; Rule 4 removed | ⬅️ **next** |

Full reasoning: `docs/engineering-mindset/week-3-AI-Assistant.md`.

---

## PR-11a — Prompt Ownership

### Concept

**Separating content from the code that composes it.**

### The engineering problem

`_SYSTEM_PROMPT` and `_HUMAN_PROMPT` are module constants inside
`data/src/generation_service.py`. That file's job is *composing a chain*. Prompt wording is
*content* — it changes when answering policy changes, which has nothing to do with how the
chain is wired. Two reasons to change, one file.

Worse: **Rule 4 — "under 3 sentences" — is still live.** It was a temporary constraint added
to keep test iterations fast, moved verbatim during PR-10 on purpose (moving text and
rewriting text are separate concerns). It is currently truncating every answer the
application produces.

### Features

* Prompts move to their own module
* Rule 4 removed; answer-length policy stated deliberately or not at all
* No behaviour change beyond the Rule 4 removal

### Explicitly NOT in this PR

**Configurable prompts.** Making prompts settable at runtime is a *configuration* concern and
belongs to PR-14a. This PR only decides **who owns the text**, not **who may change it**.

### Interview Topics

* Why is a prompt a configuration artifact rather than code?
* How do you version a prompt? What breaks when you change one in production?
* What is the difference between moving a thing and rewriting a thing, and why must they be
  separate diffs?

---

# WEEK 4 — Production Readiness

Turn a prototype into an application.

**Rule for this week: every PR teaches exactly one engineering concept.** If a PR needs two
sentences to say what it taught, it is two PRs.

| PR | Concept |
| --- | --- |
| **12a** | Asynchronous Execution |
| **12** | State Management |
| **13** | Memory Architecture |
| **14a** | Configuration |
| **14b** | Observability |
| **15** | Reliability Engineering |
| **16** | Shipping Software |

> **On the numbering.** Streaming is inserted as **PR-12a**, not as a new PR-12. Renumbering
> would shift five PRs already referenced in commit messages and published posts. An irregular
> number costs less than a broken reference.

---

## PR-12a — Streaming

### Concept

**Asynchronous execution — and what it costs the checks that run after generation.**

### The engineering problem

The user stares at a spinner for the entire generation. Total latency is unchanged by
streaming; **perceived** latency collapses. Time-to-first-token is the metric, not
time-to-completion.

The interesting part is not `.stream()`. It is the collision with output guardrails, which
makes the distinction PR-11c forced out — **validator vs sanitizer** — load-bearing for the
first time:

```
non-streaming:   [ generate whole answer ] → [ check it ] → [ show it ]
streaming:       [ show it as it arrives ] → [ ...check it with what? ]
```

* A **sanitizer** repairs the answer. Citation-marker resolution is a transform.
* A **validator** rejects the answer. Safety and relevance need the whole thing — and
  **you cannot unsay a token you have already streamed.**

There is a second trap: a marker does not arrive as a marker. It arrives as `[`, then `1`,
then `]`, possibly in three separate chunks. A per-token resolver sees a bare `[` and has
nothing to match.

This PR is the payoff for PR-10 — because the chain is a Runnable, `.stream()` is available
without editing orchestration code. That is the claim Week 3 made. This PR tests it.

### Features

* Stream tokens from the existing chain to the UI
* Decide and document what happens to each output guardrail under streaming
* Resolve citation markers after the stream completes
* Preserve token usage and latency reporting (streaming changes where that metadata arrives)

### Interview Topics

* What does streaming actually improve, and what does it not?
* How do you validate output you have already shown the user?
* What did LCEL buy you here that a hand-written loop would not have?

---

## PR-12 — Chat History

### Concept

**State management — what an application remembers, for how long, and for whom.**

### The engineering problem

Not "we lack a history feature." Three live defects in `app.py`:

**A — the answer is transient.** `response` is a local inside `if st.button("Ask")`. Streamlit
reruns the whole script on *any* widget interaction, so changing the document filter or the
chunk-preview input destroys an answer you paid an LLM call for.

**B — two parts of the app disagree about whether a knowledge base exists.** The metrics panel
is gated on `st.session_state.knowledge_base`. `ask()` is gated on nothing — it reads FAISS and
BM25 off disk. A fresh browser tab shows "no knowledge base" and answers questions correctly at
the same time. Two sources of truth, one screen.

**C — the wrong thing is cached.** Full embeddings are held in session state while already
persisted in `storage/my_index.index` — a per-user copy of every vector in process memory, so
that a metrics panel can print a number.

Every one of those is a value sitting in the wrong band:

```
┌─ transient ──────────┐  dies at end of run     response, filters
├─ session ────────────┤  per user, in RAM       knowledge_base, last_upload_signature
└─ persistent/global ──┘  all users, on disk     storage/*.index, metadata_catalog.json
```

### Features

* A chat turn persisted as a record — question, answer, sources, tokens, latency
* Answers survive rerun; history renders outside the button branch
* Defect B resolved: one source of truth for "a knowledge base exists"
* Defect C resolved: stop holding embeddings in session state

### Boundary constraint

**This PR must not touch `data/src/`.** State is a framework concern. The moment it reaches
into the domain layer, it has become PR-13.

### Interview Topics

* How do you decide what belongs in session state?
* What is `st.session_state` actually, and where does it live?
* What happens to all of this state when you run two replicas behind a load balancer?

---

## PR-13 — Conversation Memory

### Concept

**Memory architecture — what the model is conditioned on.**

### The engineering problem

Retrieval is stateless. Ask *"what is RRF?"*, then *"why that constant?"* — the second query
embeds to nothing useful, because "that constant" appears in no document. The retriever never
saw the first turn.

PR-12 made the *application* remember. This PR is a different question: **which parts of that
history reach the retriever, which reach the LLM, and which reach neither?** They are not the
same answer, and conflating them is the standard mistake.

History is also unbounded, and the context window is not. Something must decide what to drop.

### Features

* Follow-up questions retrieve correctly
* An explicit decision on how history conditions retrieval vs generation
* A bounded strategy for history that outgrows the context window

### Interview Topics

* How does a RAG system handle follow-up questions?
* Why does feeding raw chat history to the retriever perform badly?
* What is your eviction policy, and what breaks when it evicts the wrong turn?
* Difference between application state and model memory — in one sentence.

---

## PR-14a — Configuration

### Concept

**Configuration — separating what the system does from how it is tuned.**

### The engineering problem

`TOP_K = 3` is a module constant in `data/src/rag.py`. Model names are hardcoded. Chunk size,
overlap, the RRF constant, and prompt text are all buried in the code that uses them.

Every one of those is a value someone may need to change **without a code change** — and every
one currently requires editing a source file and redeploying. Tuning retrieval quality should
not be a commit.

### Features

* Config file plus environment variables, with a clear precedence order
* `TOP_K`, model names, chunk parameters, RRF constant externalized
* **Configurable prompts** — the half of PR-11 deliberately deferred to here
* Validation at startup: bad config fails loudly, not on the first request

### Interview Topics

* Config file vs environment variables vs database — when each?
* What must never go in a config file?
* Why validate configuration at startup instead of at point of use?

---

## PR-14b — Observability

### Concept

**Observability — what a running system can tell you about itself.**

### The engineering problem

A user says *"the answers got worse."* Right now there is nothing to look at. You cannot
determine whether retrieval returned bad chunks, the prompt changed, the model degraded, or the
user asked a harder question.

PR-10 already recorded the failure mode that makes this urgent: a silently-dropped `{context}`
variable produced fluent, confident answers built on **no retrieved context at all**, and raised
no exception. That class of bug is invisible without instrumentation.

### Features

* Structured logging across the pipeline stages
* A request identifier that correlates retrieval, generation, and guardrail decisions
* Per-stage timings
* Guardrail decisions logged — what was rejected or stripped, and why

### Interview Topics

* Logging vs metrics vs tracing — what does each answer?
* What do you log, and what must you never log, in an LLM application?
* How would you detect a silent quality regression?

---

## PR-15 — Error Handling & UX

### Concept

**Reliability engineering — how the system behaves when a dependency fails.**

### The engineering problem

If Ollama is unreachable the chain raises and Streamlit renders a Python traceback to the user.
This was deliberately deferred from PR-10 rather than silently ignored — this is where it comes
due.

Every external call in this system can fail: embedding, retrieval, generation. Each needs a
decision — retry, degrade, or fail — and *"retry everything"* is wrong. Retrying a
non-idempotent or already-failing call turns one outage into an amplified one.

### Features

* Every external failure surfaces as a human-readable message, never a traceback
* An explicit retry/degrade/fail decision per external call
* Loading indicators and empty states
* Timeouts on the LLM call

### Interview Topics

* Which failures should you retry, and which must you never retry?
* What is exponential backoff, and why jitter?
* Fail fast vs degrade gracefully — how do you choose?
* Your vector store is up but the LLM is down. What does the user see?

---

## PR-16 — Documentation & Deployment

### Concept

**Shipping software — making it run somewhere that is not your laptop.**

### The engineering problem

Right now this application runs on one machine, against a locally-installed Ollama, with a
FAISS index on the local filesystem. None of those assumptions survive deployment. Discovering
which ones break — and why — *is* the lesson.

### Features

* README that a stranger can follow to a running app
* Architecture diagram
* Deployed application
* Documented decision on what happens to the local-model and local-index assumptions

### Interview Topics

* What broke when you deployed, and why?
* Where does the vector index live when the app runs on ephemeral storage?
* What would you change to serve a hundred concurrent users?

---

### Carried-over defects — where each one lands

Logged during Weeks 2–3, deliberately not fixed at the time. Each has an owner now:

| Defect | Lands in |
| --- | --- |
| `metadata_catalog.json` persists a dead `/tmp/...` path — the upload is deleted at ingestion | PR-14b (it is a data-honesty problem) or Stage 2 storage |
| `_check_empty_response` mutates its input while sibling guardrails construct fresh objects | PR-15 — inconsistent contract across the guardrail family |
| No error handling around the LLM call | PR-15 |
| `app.py` success caption predates citations | PR-12 (UI already changing) |
| Level 2 citations — "open the PDF at page 3" | Stage 2 — a retention and storage decision, not a prompt one |
| LLM-judged relevance and safety (`_validate_relevance`, `_check_safety` stubs) | Stage 2 |

---

### Final Project Structure

```text
Knowledge Assistant v1
│
├── Upload PDFs
├── Chunk Documents
├── Generate Embeddings
├── Store in FAISS
├── Retrieve Similar Chunks
├── Hybrid Search
├── Metadata Filtering
├── Guardrails
├── LCEL Pipeline
├── Inline Citations
├── Streaming
├── Chat History
├── Conversation Memory
├── Config Management
├── Logging
├── Error Handling
└── Deployment
```

---

### Why I like this roadmap

Each PR satisfies four goals simultaneously:

| Goal                 | Outcome                                                                           |
| -------------------- | --------------------------------------------------------------------------------- |
| **Engineering**      | One coherent feature is added to the application.                                 |
| **Learning**         | You deeply understand one core GenAI/RAG concept.                                 |
| **Interview Prep**   | Every PR maps to one or more interview topics you can confidently explain.        |
| **Content Creation** | Every PR becomes a focused live stream, GitHub contribution, and LinkedIn update. |

This also sets us up perfectly for **Stage 2**, where we'll evolve this same application into a production-ready AI assistant with Spring Boot integration, PostgreSQL, Docker, JWT authentication, and LangGraph instead of throwing away the work from Stage 1.
