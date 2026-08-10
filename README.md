# 🦈 Knowledge Assistant

A private, local-first RAG application. Upload PDFs or Markdown, ask questions, get answers
**with inline citations that are verified deterministically** — no data leaves your machine.

Built from scratch over four weeks, one engineering concept per pull request. Every
architectural decision, and every alternative rejected along the way, is written down in
[`docs/engineering-mindset/`](docs/engineering-mindset/).

```
You: How does the fusion step combine the two retrievers?

Reciprocal Rank Fusion scores each document by the sum of 1/(k + rank) across every
retriever that returned it, with k defaulting to 60 [1]. Because it uses rank rather
than score, it can merge results from retrievers whose scores are not comparable [2].

Sources:  [1] retrieval-design.md   ·   [2] hybrid-search-notes.pdf
```

---

## What it does

| | |
| --- | --- |
| **Hybrid retrieval** | Dense (FAISS) + sparse (BM25), fused with Reciprocal Rank Fusion |
| **Verified citations** | Every `[n]` is checked against the sources actually issued — invented markers are stripped, not shown |
| **Streaming** | Tokens appear as they generate, buffered so a citation marker is never split mid-flush |
| **Conversation memory** | A rolling summary conditions *both* retrieval and generation, computed off the critical path |
| **Guardrails** | Empty input, prompt injection, empty context, empty response, poisoned summaries |
| **Metadata filtering** | Restrict retrieval to specific documents |
| **Observability** | Per-turn trace in the UI and a rotating log file — counts and verdicts, never document content |
| **Graceful degradation** | If the model is unreachable, you still get the passages retrieval found |

Everything runs against a local [Ollama](https://ollama.com). No API keys, no telemetry, no
uploads.

---

## Running it

**Prerequisites**

- Python 3.11+
- [Ollama](https://ollama.com) running locally

```bash
ollama pull llama3.2          # generation and summarisation
ollama pull embeddinggemma    # embeddings
```

**Install and run**

```bash
git clone <this-repo>
cd knowledge-assistant

python -m venv .venv
source .venv/bin/activate     # Windows: .venv\Scripts\activate
pip install -r requirements.txt

streamlit run app.py
```

Open the URL Streamlit prints, upload a PDF or `.md` file, press **Build Knowledge Base**, then
ask a question.

> **Note on the virtualenv name.** This repo was developed with the environment in a directory
> called `.env`. That name collides with the conventional `.env` *file*, which is why
> configuration is read from environment variables directly and `python-dotenv` is deliberately
> not used. If you create your venv as `.venv` (as above), that collision does not apply to you.

---

## Architecture

Two things to notice: the framework owns exactly one region, and the write path runs after the
user already has their answer.

```
                        ┌──────────────── app.py ────────────────┐
                        │  chat UI · session state · typewriter  │
                        └────────────────────┬───────────────────┘
                                             │ question, filters, summary
┌────────────────────────────────────────────▼────────────────────────────────────────┐
│  rag.py — ORCHESTRATION: order, timing, and what reaches the user                    │
│                                                                                     │
│   validate_input ──► retrieve ──► validate_context ──► generate ──► validate_output  │
│        │                │                │                │              │          │
│        │                │                │                │              │          │
│   plain Python     FAISS + BM25     plain Python      LCEL chain     plain Python    │
│                       + RRF                          ◄── the ONLY framework region   │
│                                                                                     │
│   ── critical path ends when the last token is flushed ──────────────────────────    │
│   SummarizationService  ──►  sanitize  ──►  validate  ──►  accept or keep previous   │
└─────────────────────────────────────────────────────────────────────────────────────┘
```

**The LCEL chain** — deliberately ends at the LLM, with no `StrOutputParser`:

```
{sources, user_query, history}
        │
   RunnableParallel ── context     ← render <source id="1" file="…"> blocks
        │           ── user_query
        │           ── history
        ▼
  ChatPromptTemplate     system: answering rules   ·   human: <history> <context> question
        ▼
     ChatOllama          → AIMessage, translated into GenerationResponse by the service
```

`StrOutputParser` would return `message.content` and discard `usage_metadata` and
`response_metadata` — the token counts, finish reason, and latency the UI reports. Translating
the framework's type into the domain type happens at the service boundary instead.

**Layout**

```
app.py                        chat UI, session state, typewriter rendering
data/src/
  rag.py                      orchestration, streaming buffer, degradation
  config.py                   every tunable value, from environment variables
  observability.py            per-turn trace collector + rotating file log
  resilience.py               retry classification, backoff, DependencyError
  prompts.py                  all prompt text
  generation_service.py       the LCEL chain
  summarization_service.py    the rolling conversation summary
  guardrails/                 input · context · output · shared text policy
  retriever/                  dense · sparse · metadata filtering · RRF fusion
  storage/                    FAISS · BM25 · embeddings
  strategy_pattern/           chunking strategies
  factory_pattern/            document loaders
storage/                      runtime state: indexes, catalog, app.log  (git-ignored logs)
```

---

## Configuration

Everything is an environment variable with a working default — see
[`data/src/config.py`](data/src/config.py). Bad values fail at **startup**, not on the first
question.

| Variable | Default | |
| --- | --- | --- |
| `OLLAMA_BASE_URL` | `http://localhost:11434` | |
| `GENERATION_MODEL` | `llama3.2:latest` | |
| `SUMMARIZATION_MODEL` | `llama3.2:latest` | separate key — summarising is a cheaper job |
| `EMBEDDING_MODEL` | `embeddinggemma:latest` | changing this invalidates the index |
| `TOP_K` | `3` | chunks retrieved per question |
| `RRF_K` | `60` | rank-fusion damping constant |
| `CHUNK_SIZE` / `CHUNK_OVERLAP` | `600` / `300` | changing these invalidates the index |
| `STORAGE_DIR` | `./storage` | indexes, catalog, and logs |
| `FLUSH_FLOOR` | `20` | chunks buffered before a flush |
| `LLM_MAX_ATTEMPTS` | `3` | attempts, not retries |
| `LOG_RETENTION_DAYS` | `7` | rotated files kept |

`MARKER_MAX` is **derived** from `TOP_K`, not configurable — the longest valid citation marker
is `[` + `TOP_K` + `]`, so exposing both would let them disagree and silently truncate
citations. *If a value can be computed from another value, it is not configuration.*

---

## Design decisions

The reasoning behind each PR — including alternatives considered and rejected — is in
[`docs/engineering-mindset/`](docs/engineering-mindset/). A few worth reading on their own:

| | |
| --- | --- |
| [Week 3](docs/engineering-mindset/week-3-AI-Assistant.md) | Why LCEL was adopted for a *named* problem, not for being modern · why citation labels are request-scoped with a materialised mapping · sanitize-don't-reject |
| [Week 4](docs/engineering-mindset/week-4-AI-Assistant.md) | Why streaming trades enforceability for perceived latency · why memory feeds retrieval and not just the model · why every sanitizer is a quality sensor |

A running theme worth stating once: **a framework may own composition; it must not own policy.**
Guardrails, retrieval, buffering, and memory are all plain Python. Only the prompt-to-model
composition is declarative — which is why the guardrails are testable with a plain `assert` and
zero framework imports.

---

## Known limitations

Stated deliberately. Each was a decision with reasons, not an oversight.

**Topic change degrades retrieval.** The conversation summary is prepended to the retrieval
query, and three sentences of summary outweigh a six-word question. Ask about a new subject on
turn four and you may retrieve chunks about turns one to three. Clearing the conversation resets
it. The fix — cosine-compare the question against the summary and drop it below a threshold —
needs a magic number there is no data to tune yet.

**No relevance floor.** `TOP_K` is a fixed count, so retrieval returns three chunks whether or
not three relevant ones exist. A question with two good matches gets a third irrelevant one.

**Rule 6 is prompt compliance, not a guarantee.** The model is told to use conversation history
only to resolve references, never as a source of facts. A small model does not always obey. The
symptom — an answer with no citations — is counted and visible in the trace, but not prevented.

**Citation *supportiveness* is unchecked.** Whether a cited chunk actually backs the claim is
judgment, not structure, and needs an LLM judge. Only citation *existence* is verified today,
which is deterministic and exact.

**Single-user state.** Conversation history and the summary live in Streamlit session state, in
memory. Multiple replicas behind a load balancer would not share them.

**No circuit breaker.** Retries are bounded per request but there is no global budget. With one
local user and one local Ollama there is no herd to protect against; at scale there would be.

**Level 2 citations are not possible.** Uploads are written to a temp file and deleted after
ingestion, so "open the source PDF at page 3" would need a retention decision — where uploads
live, who cleans them up, and whether keeping user documents is permitted at all.

---

## Not deployed

This runs locally by design. Deployment would need decisions this project has not made:
where the FAISS index lives when the filesystem is ephemeral, whether Ollama is reachable from
the host, and what session state means across replicas. Those are Stage 2 questions.

---

## Development journey

Built in small, reviewable pull requests — each introducing exactly one engineering concept.
The full plan and rationale is in [`PR-Journey.md`](PR-Journey.md).

| Week | | |
| --- | --- | --- |
| **1** | PR-1 → PR-6 | Core RAG — loading, chunking, embeddings, FAISS, retrieval, answering |
| **2** | PR-7 → PR-9 | Better retrieval — hybrid search, metadata filtering, guardrails |
| **3** | PR-10 → PR-11a | LCEL composition, citations, deterministic verification, prompt ownership |
| **4** | PR-12a → PR-16 | Streaming, state, memory, configuration, observability, reliability, docs |

A per-PR summary is in [`CHANGELOG.md`](CHANGELOG.md).

---

## Project documents

| | |
| --- | --- |
| [`PR-Journey.md`](PR-Journey.md) | The full plan — every PR, its concept, and the problem it solves |
| [`docs/engineering-mindset/`](docs/engineering-mindset/) | Design decisions, rejected alternatives, and mistakes made |
| [`CHANGELOG.md`](CHANGELOG.md) | What changed, PR by PR |
| [`CONTRIBUTING.md`](CONTRIBUTING.md) | How to use this repo — and why arguing with a decision beats a patch |
| [`SECURITY.md`](SECURITY.md) | Threat model for a local-first app, and what is known-and-accepted |
| [`CODE_OF_CONDUCT.md`](CODE_OF_CONDUCT.md) | Contributor Covenant 2.1 |
| [`LICENSE`](LICENSE) | MIT |

---

*Built in public. Every decision recorded — including the ones that turned out to be wrong.*
