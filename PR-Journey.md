

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

### Features

* Central prompt template
* Configurable prompts
* Better citations
* Better formatting

---

# WEEK 4 — Production Readiness

Turn a prototype into an application.

---

## PR-12 — Chat History

### Features

* Previous questions
* Previous answers
* Sidebar history

### Concepts

* Conversation state
* Session state

---

## PR-13 — Conversation Memory

### Features

* Basic conversational context
* Follow-up questions
* Context retention

### Concepts

* Memory
* Conversation chains

---

## PR-14 — Configuration & Logging

### Features

* Config file
* Logging
* Environment variables
* Better project structure

### Concepts

* Observability
* Configuration management

---

## PR-15 — Error Handling & UX

### Features

* Friendly errors
* Loading indicators
* Empty state
* Missing PDF handling

### Concepts

* Robust engineering
* User experience

---

## PR-16 — Documentation & Deployment

### Features

* Better README
* Screenshots
* Architecture diagram
* Deploy application
* Final cleanup

### Concepts

* Documentation
* Deployment
* Project presentation

---

# Final Project Structure

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
├── Chat History
├── Conversation Memory
├── Logging
├── Config Management
├── Error Handling
└── Deployment
```

---

# Why I like this roadmap

Each PR satisfies four goals simultaneously:

| Goal                 | Outcome                                                                           |
| -------------------- | --------------------------------------------------------------------------------- |
| **Engineering**      | One coherent feature is added to the application.                                 |
| **Learning**         | You deeply understand one core GenAI/RAG concept.                                 |
| **Interview Prep**   | Every PR maps to one or more interview topics you can confidently explain.        |
| **Content Creation** | Every PR becomes a focused live stream, GitHub contribution, and LinkedIn update. |

This also sets us up perfectly for **Stage 2**, where we'll evolve this same application into a production-ready AI assistant with Spring Boot integration, PostgreSQL, Docker, JWT authentication, and LangGraph instead of throwing away the work from Stage 1.
