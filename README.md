# 🧠 Project: Knowledge Assistant v1

> Building a production-ready RAG (Retrieval-Augmented Generation) application from scratch.
>
> This repository is developed incrementally over **4 weeks**, with each branch representing a major milestone in the journey.

---
## 🛤️ Journey Philosophy

This repository is intentionally built in small, reviewable Pull Requests.

Each Pull Request introduces exactly one major concept, making it easy for anyone to:

- Follow the learning journey
- Review architectural decisions
- Understand how a production RAG system evolves over time
- Recreate the project from scratch

The goal isn't just to build an AI application—it's to document the engineering process behind it.


## 🚀 Learning Roadmap

### 🌱 Week 1 — Core RAG

**Branch:** `week-1-core-RAG`

**Goal:** Build a fully functional RAG pipeline capable of answering questions from uploaded PDF documents.

#### Progress

- [ ] PR-01 — Project Bootstrap
- [ ] PR-02 — PDF Upload & Loading
- [ ] PR-03 — Chunking Engine
- [ ] PR-04 — Embedding Pipeline
- [ ] PR-05 — FAISS Vector Store
- [ ] PR-06 — Basic Question Answering

#### Outcome

By the end of Week 1, the application will:

- 📄 Upload one or more PDF documents
- ✂️ Split documents into chunks
- 🧠 Generate embeddings
- 🗄️ Store embeddings in FAISS
- 🔍 Retrieve relevant chunks
- 💬 Answer user questions using the uploaded documents

---

### 🚀 Week 2 — Better Retrieval

**Branch:** `week-2-better-retrieval`

**Goal:** Improve retrieval quality to make the assistant more production-ready.

#### Progress

- [ ] PR-07 — Hybrid Search
- [ ] PR-08 — Metadata Filtering
- [ ] PR-09 — Guardrails

#### Outcome

The assistant will now support:

- 🔀 Hybrid Search (Dense + Sparse Retrieval)
- 🏷️ Metadata-based Filtering
- 🛡️ Prompt Injection Protection
- ✅ Safer and more accurate responses

---

### 🏗️ Week 3 — LCEL Refactor

**Branch:** `week-3-LCEL-refactor`

**Goal:** Refactor the application using LangChain Expression Language (LCEL).

#### Progress

- [ ] PR-10 — LCEL Pipeline
- [ ] PR-11 — Prompt Refactoring

#### Outcome

The project will evolve from helper functions to a modular pipeline:

```text
Retriever
      │
      ▼
Prompt
      │
      ▼
LLM
      │
      ▼
Output Parser
```

Benefits:

- Better architecture
- Easier debugging
- Improved composability
- Production-style LangChain implementation

---

### 🏁 Week 4 — Production Readiness

**Branch:** `week-4-production-readiness`

**Goal:** Transform the prototype into a production-quality application.

#### Progress

- [ ] PR-12 — Chat History
- [ ] PR-13 — Conversation Memory
- [ ] PR-14 — Logging & Configuration
- [ ] PR-15 — Error Handling
- [ ] PR-16 — Documentation & Deployment

#### Outcome

The final application will include:

- 💬 Chat History
- 🧠 Conversation Memory
- 📊 Logging
- ⚙️ Configuration Management
- 🚨 Robust Error Handling
- 📖 Complete Documentation
- ☁️ Deployment

---

## 📈 Project Evolution

```text
Week 1
──────────────
PDF Upload
      │
      ▼
Chunking
      │
      ▼
Embeddings
      │
      ▼
FAISS
      │
      ▼
Question Answering

                ↓

Week 2
────────────────────────
Hybrid Search
      │
      ▼
Metadata Filtering
      │
      ▼
Guardrails

                ↓

Week 3
────────────────────────
LCEL Refactor
      │
      ▼
Cleaner Architecture
      │
      ▼
Better Prompt Pipeline

                ↓

Week 4
────────────────────────
Chat History
      │
      ▼
Conversation Memory
      │
      ▼
Logging
      │
      ▼
Configuration
      │
      ▼
Error Handling
      │
      ▼
Deployment
```

---

## 🎯 Final Features

- ✅ PDF Upload
- ✅ Recursive Chunking
- ✅ Embeddings
- ✅ FAISS Vector Store
- ✅ Semantic Search
- ✅ Hybrid Search
- ✅ Metadata Filtering
- ✅ Guardrails
- ✅ LCEL Architecture
- ✅ Chat History
- ✅ Conversation Memory
- ✅ Logging
- ✅ Configuration Management
- ✅ Error Handling
- ✅ Deployment

---

## 📚 Learning Objectives

This project is designed to teach:

- Retrieval-Augmented Generation (RAG)
- Vector Databases
- Embeddings
- Similarity Search
- Hybrid Search
- Metadata Filtering
- Guardrails
- LangChain Expression Language (LCEL)
- Production-ready AI application architecture

---

> Every Pull Request represents a single engineering milestone, making it easy to follow the evolution of the project from a minimal RAG prototype to a production-ready AI application.