# Week 4 — Production Readiness

> Turn a prototype into an application.

Weeks 1–3 built something that works. Week 4 asks the questions that only matter once other
people use it: how long does the user wait, what does the application remember, what is
tunable without a redeploy, what happens when a dependency dies, and can anyone but me run it.

The rule for this week is **one engineering concept per PR**. If a PR needs two sentences to
say what it taught, it is two PRs.

| PR | Concept |
| --- | --- |
| **11a** | Prompt ownership *(carried over from Week 3)* |
| **12a** | Asynchronous execution |
| **12** | State management |
| **13** | Memory architecture |
| **14a** | Configuration |
| **14b** | Observability |
| **15** | Reliability engineering |
| **16** | Shipping software |

**On the numbering.** Streaming was never in `PR-Journey.md` — it existed in my Stage-1 plan
and in the final feature list, but no PR owned it. Inserting it as a new PR-12 would have
renumbered five PRs already referenced in commit messages and published posts. It became
**PR-12a** instead. An irregular number costs less than a broken reference.

---
---

## PR-11a Discussion — Prompt Ownership

Week 3 closed with this deliberately deferred. It is small, and its whole value is in one
decision plus one deletion.

### Problem Statement

`_SYSTEM_PROMPT` and `_HUMAN_PROMPT` were module constants inside `generation_service.py`.
That file's job is **composing a chain**. Prompt wording is **content** — it changes when
answering policy changes, which has nothing to do with how the chain is wired.

Two reasons to change, one file. That is the same SRP argument PR-10 used to split the prompt
into system and human messages, applied one level up: not *"which message does this text belong
in"* but *"which file does this text belong in."*

And a live defect was riding along. **Rule 4 — "under 3 sentences" — was still in production.**
It was a temporary constraint added so my test loop would be fast, moved verbatim during PR-10
on purpose, and it had been truncating every answer the application produced ever since.

---

### Design Decision #13 — Location Now, Configurability Later

The obvious upgrade is to make prompts loadable from a YAML or `.env` file so a non-engineer
can change answering policy without a commit. I deliberately did not do that.

| | Buys | Costs |
| --- | --- | --- |
| **Python module** *(chosen)* | one place to edit; zero new failure modes | changing a prompt is still a commit and a redeploy |
| **External file** | policy editable without shipping code | who loads it, when, and what happens when it is missing or malformed — all new failure modes; a stray `{` in an unchecked file becomes a runtime template error |

The reason for choosing the smaller change is not caution. It is that **PR-14a owns
configuration**, and pre-empting it here would have left PR-14a with nothing but a file format
to pick.

What PR-11a actually built is a **seam**: a single place where the prompt lives, so that when
configurability arrives it lands in one file instead of being carved out of `generation_service`
under pressure.

> **Engineering Principle**
> Make the change you know is coming *cheap*. Do not make it *early*. Building configurability
> before anything needs it is speculative generality; creating the seam it will need is not.

**The narrow claim, and why it matters.** My first framing was *"PR-14a will only have to touch
the prompt module."* That is not true, and it is the kind of overstatement an interviewer
catches by reading one line:

```python
_prompt = ChatPromptTemplate.from_messages([...])   # built at class-definition time
_chain  = (... | _prompt | _llm)                    # chain compiled at import
```

The prompt is **baked into a chain constructed once, at import**. A runtime-configurable prompt
cannot be absorbed by the prompt module alone; it has to deal with that eager construction. So
the honest claim is the narrow one:

> PR-11a makes prompt **text** a one-file change. It does not make prompt **behaviour** a
> one-file change.

That remaining problem belongs to PR-14a, and discovering it there is the lesson there.

**Rejected: an accessor function.** `get_system_prompt()` returning the constant looks like it
future-proofs the seam. It does not — the chain would still evaluate it once at import, so the
wrapper buys nothing today while adding indirection. A rejected wrapper you can explain is
worth more than a wrapper you built.

---

### Rule 4 — Deleting a Constraint Without Replacing It

Removing the rule was easy to justify: it was a *development* artifact, and the application is
now being judged at production quality.

But that argument only answers *why the rule must go*. It says nothing about *what the product
actually wants*, and those are two different questions. I initially reached for replacements:

| Proposed replacement | Why it was wrong |
| --- | --- |
| "Stop when there is no relevant context left" | Already Rule 2 — and `validate_context()` enforces it *harder*, before generation even runs |
| A resource / length budget in the prompt | A prompt rule is a **request** the model may ignore. A token cap is an **enforcement**. If a hard ceiling is wanted, it is `num_predict` on `ChatOllama` — a model parameter, therefore PR-14a configuration, not prompt text |

> **Engineering Principle**
> Never write a prompt rule for something the runtime can enforce. Asking the model politely to
> respect a budget is strictly worse than setting the budget.

**Decision: no length policy at all.** Not a residue — a choice. Verified afterwards by running
it: answers did *not* get longer, because with this chunk size and this model, replies are
naturally short. The rule had been cutting off answers that were never going to be long anyway.

---

### Interview Takeaway

**Where do prompts belong in a codebase?**

> Not next to the code that composes the chain — they change for different reasons. I moved them
> to their own module, which is a seam rather than a feature: making them runtime-configurable
> is a separate concern that belongs with the rest of my configuration work. I'd also be careful
> about the claim — the chain compiles the prompt at import, so moving the text makes *text* a
> one-file change, not *behaviour*.

---
---

## PR-12a Discussion — Streaming

### Problem Statement

The user watches a spinner for the entire generation.

The first thing to get right is what streaming does **not** do: it does not make generation
faster. Total latency is identical. What changes is **time-to-first-token** — the user sees
progress in a few hundred milliseconds instead of after the whole answer exists.

> Streaming is a **perceived** latency fix. Anyone who says it speeds up the model has not
> measured it.

This PR is also the bill coming due for Week 3. PR-10's entire justification was:

> Execution modes belong to the composition, not to each step. Because a chain of Runnables is
> itself a Runnable, `.stream()` applies to the whole pipeline for free.

Now I find out whether that was true. It half was. `.stream()` did come for free — **the chain
required zero changes.** What was not free was everything my own architecture had built on the
assumption that an answer arrives all at once.

---

### The Real Problem — My Own Contract, Not the Framework

```
rag.py — ask() before this PR

  validate_input(query)        → may reject
  RetrievalService.retrieve()
  validate_context(...)        → may reject
  GenerationService.generate_answer()   ← blocks until a whole answer exists
  validate_output(response)    → may reject          ▲
  return GenerationResponse                          │
                                    everything downstream of generation
                                    assumes a COMPLETE answer
```

`ask()` is typed `-> GenerationResponse`. A `GenerationResponse` is a **finished** thing:
`answer`, `token_usage`, `finish_reason`, `latency`, `sources`. Streaming means the answer does
not exist when I need to start showing it.

Two consequences, and keeping them separate is what made the design tractable:

**(a) The complete response is still required — it just arrives late.** `usage_metadata` and
`response_metadata` come on the *final* chunk. Token counts, finish reason, and latency are
simply not knowable until the stream is over. Streaming does not remove the response object; it
means the user reads the answer *before* it exists as a domain object.

**(b) `validate_output` can no longer reject.** The tokens have been shown. There is no
un-saying them.

That second one is the actual subject of this PR.

---

### Core Thoughts — What I Believed Going In

I believed streaming was a UI change: swap `.invoke()` for `.stream()`, hand the generator to
`st.write_stream`, done. The demo I wrote to check the metadata question does exactly that in
25 lines, and it works.

What that framing misses is that **every output guardrail I built in Week 3 assumed it ran
before the user saw anything.** Streaming inverts that ordering, and no amount of framework
support fixes an inverted ordering.

The correct framing, which took the whole design discussion to reach:

> Streaming is not `token → screen`.
> It is `token → policy → screen`.

You cannot run policy over data you have already flushed. So something must be held back.

---

### Design Decision #14 — Streaming Is a Peer of `ask()`, Not a Variant

Three shapes were possible:

| Shape | Verdict |
| --- | --- |
| `ask(query, filters, stream=True)` | ❌ Returns a `GenerationResponse` *or* a generator depending on an argument. Two return types from one signature, so every caller must branch on the flag anyway — the branch moved, it did not disappear. Classic flag-argument smell. |
| `ask()` always streams; the blocking path is `"".join(...)` over it | ❌ Forces a buffering concern onto callers that never asked for one, and makes the simple path pay for the complex one. |
| **`ask()` and `ask_stream()` as peers** | ✅ Chosen |

Two functions, two honest signatures, one shared prefix.

The shared prefix — input guardrail, retrieve, context guardrail — was extracted rather than
duplicated. Two peers copying three steps means two places to edit when input guardrails change,
and one of them will eventually be missed:

```python
def _retrieve_context(query, filters) -> tuple[list[Document] | None, GenerationResponse | None]:
```

**Why a tuple rather than an exception.** A guardrail rejection is an **expected** outcome — the
system is working correctly when it refuses. Exceptions model the *unexpected*. Using one here
would hide the second path from the signature and make `ask()` read as though it always
succeeds.

> **Engineering Principle**
> Expected outcomes belong in the return type. Exceptions are for the outcomes you did not plan
> for.

---

### Design Decision #15 — Buffer-and-Delay, and Where It Lives

If policy must run before text reaches the screen, then text must be held back. The mechanism
is a **lookahead window**: keep some output behind the live edge so there is always something
to inspect before it is committed.

The question that decides the architecture is *who owns the window*.

```
GenerationService  ← owns HOW the model executes      (.stream() vs .invoke())
rag.py             ← owns WHEN text may reach the user (buffering, flush timing, guardrails)
app.py             ← owns HOW it looks while arriving  (animation)
```

Buffering is **sequencing policy**, and sequencing is exactly what `rag.py` already did for the
blocking path. So `GenerationService.stream_answer()` returns the raw chunk iterator and knows
nothing about buffers; `rag.py` consumes it and decides what escapes.

**A mechanical trap worth recording.** `stream_answer` must return *both* the chunk iterator and
the `sources` list — the caller needs `sources` to build the response and the UI needs them to
resolve `[1]` to a filename.

```python
@classmethod
def stream_answer(cls, user_query, retrieved_documents):
    sources = _label_sources(retrieved_documents)
    chunks = cls._chain.stream({"sources": sources, "user_query": user_query})
    return sources, chunks          # a plain function that RETURNS an iterator
```

If this method contained a `yield` anywhere, calling it would return a generator object and
`sources` could never be retrieved — it would have to be smuggled out through a mutable
argument. Because `.stream()` already hands back an iterator, the method stays a plain function.

> **A generator function and a function that returns a generator are different things.** The
> first can only ever give you one value.

---

### Design Decision #16 — The Flush Boundary, Derived From the Grammar

This is the decision the PR turns on.

Week 3 already recorded that a marker does not arrive as a marker — it arrives as `[`, then `1`,
then `]`, possibly in three separate chunks. My first instinct in this PR was to verify
citations **chunk by chunk**, which quietly contradicted that finding.

Buffering does not fix it. It makes it **rarer**:

```
flush N   : "...dense and sparse retrieval [1"
flush N+1 : "]. BM25 scores by term frequency [4]."
```

`strip_unverified_citations` matches complete `[n]` markers. In flush N it sees `[1` — no match
— so nothing is stripped, and that text is on the user's screen permanently. It is never
re-examined.

Token-by-token this fails almost every time and I would have caught it in five minutes.
**Buffered, it fails only when a marker straddles a boundary.**

> A bug that fires one time in thirty is worse than one that fires every time, because it ships.

So the flush point must be **boundary-aware**. My first proposal for the cap was "20 tokens plus
`x` where `x <= TOP_K`." The instinct was right — the wait *is* bounded — but the number was a
guess. The better bound comes from the grammar of the thing being protected:

> A valid marker is `[` + digits + `]`. With `TOP_K = 3` the longest possible marker is `[3]` —
> three characters. Past `MARKER_MAX = 8`, an unmatched `[` **cannot** be a citation. It is
> ordinary text: `[note]`, a code sample, footnote syntax.

That turns an unbounded wait into a bound I can state and defend:

```python
def _safe_flush_point(pending: str) -> int:
    open_bracket = pending.rfind("[")

    if open_bracket == -1:                            return len(pending)   # nothing to split
    if "]" in pending[open_bracket:]:                 return len(pending)   # already closed
    if len(pending) - open_bracket > MARKER_MAX:      return len(pending)   # literal text
    return open_bracket                                                     # marker in flight
```

Note the last line flushes **everything before** the bracket rather than holding the whole
buffer. Holding it all would cost time-to-first-token and buy no extra safety.

> **Engineering Principle**
> When you need a magic number, derive it from the structure you are protecting. A number you
> can explain is a decision; a number that felt right is a liability.

This is the same problem as decoding UTF-8 from a socket: never flush half a multi-byte
sequence. Here the "sequence" is `[` … `]`.

**The coupling this creates must be stated loudly.** Sanitizing per flush is only *correct*
because `_safe_flush_point` guarantees no partial marker is in the slice. The two decisions are
load-bearing on each other. Anyone who later "simplifies" the boundary rule reintroduces the
exact defect PR-11c exists to prevent — and reintroduces it in its rare, hard-to-find form.

---

### Design Decision #17 — `StreamedAnswer`, Because One Operation Yields Two Things

The caller needs the text *as it arrives* and the finished `GenerationResponse` *afterwards*. A
generator can only deliver the first.

The common workaround — and the one my own streaming demo used — is a mutable dict the generator
writes into:

```python
usage_holder = {}                       # from demo-stream.py
...
usage_holder["metadata"] = chunk.usage_metadata
```

That works, and it is exactly the out-parameter pattern PR-11's Mistake 7 taught me to distrust:
an invisible contract, where the second value only exists if the caller happens to look in the
right place at the right time.

```python
@dataclass
class StreamedAnswer:
    tokens: Iterator[str]
    response: GenerationResponse | None = None
```

**Consumption contract:** iterate `tokens` to completion, *then* read `response`.

The neat part is the rejection case. If an input or context guardrail rejects, `tokens` is the
empty iterator and `response` is populated **immediately**. The UI does not branch:

```python
stream = ask_stream(question, filters)
st.write_stream(typewriter(stream.tokens))   # renders nothing when rejected
response = stream.response                   # the rejection, or the answer
if not response.success: ...
```

One code path for "rejected before generation" and "generated successfully" — because a rejected
request is simply a stream with no tokens in it.

> **Engineering Principle**
> When a design produces a special case, look for the framing where it stops being special.

---

### Design Decision #18 — One Place That Knows What an `AIMessage` Is

`generate_answer` used to build the `GenerationResponse` inline. Streaming needs the same
mapping, from an accumulated chunk instead of a message.

Duplicating it would have put `response_metadata.get("done_reason")` in two files — and one of
them would be `rag.py`, the orchestration layer, which has no business knowing LangChain's field
names.

```python
@classmethod
def build_response(cls, message, sources) -> GenerationResponse:
```

Both paths now translate through it. This is **INVARIANT #2 from PR-10** holding under pressure:
translate framework types into domain types at the boundary you own. The pressure was real —
inlining six lines in `rag.py` would have been the shortest diff.

`message` is allowed to be `None` (the model produced no chunks at all). That becomes an empty
answer rather than a crash, because rejecting empty answers is `_check_empty_response`'s job,
not this method's. Deciding *where* a failure is handled is as much a design act as handling it.

---

### Design Decision #19 — The Sanitizer Becomes Pure

`_strip_unverified_citations(generation_response) -> None` took a domain object. The streaming
path has no domain object yet — it has a **string**.

```python
def strip_unverified_citations(text, sources) -> str:      # pure: text in, text out
def _strip_unverified_citations(response) -> None:          # thin adapter, unchanged call site
```

This is PR-10's `_format_documents` lesson recurring: **if a function does not need the object,
it should not take the object.** The pure version is testable with a plain `assert`, callable
from both paths, and unaware of `GenerationResponse` entirely.

`validate_output()`'s call site did not change, which is the point of the adapter.

---

### Design Decision #20 — The Typewriter Is Presentation, Not Policy

Running it revealed a UX problem the design had not predicted: 20-token flushes land as visible
bursts. It reads like hiccups.

There are two ways to fix that, and choosing the wrong one is the interesting part.

| Fix | Effect |
| --- | --- |
| Lower `FLUSH_FLOOR` to 1 | ✅ Smooth. ❌ Shrinks the policy window to nothing and runs the guardrails once per token. |
| **Animate in the UI** | ✅ Smooth. ✅ Safety window untouched. |

> **Engineering Principle**
> Never weaken a safety mechanism to fix how something looks. The buffer size is a **safety**
> parameter; the render cadence is a **presentation** parameter. Tuning one must not be able to
> degrade the other.

Keeping them in different layers is what makes that guarantee structural rather than a promise.

The animation paces itself against the model rather than using a fixed delay. It measures how
long `next()` blocked — which is exactly how long the model spent producing that block — and
spreads the block's characters over that interval:

```
model slow  →  waited 0.4s for 80 chars  →  ~5ms/char  →  types while the model works
model fast  →  blocks already queued     →  waited ≈ 0 →  clamps to the 2ms floor, catches up
```

Self-correcting: falling behind means the next block is already waiting, which makes the
measured wait smaller, which speeds the typing up.

**The subtle part:** the measurement wraps `next()` specifically, not the whole loop. If it
included the sleeps, it would be measuring its own typing speed, and the pacing would lock to
whatever value it happened to start at — a feedback loop that looks like it adapts and does not.

---

### The Trade-off I Could Not Design Away

My proposal included: *if a validator fails mid-stream, stop, and maybe override what was
already sent.*

That does not hold. Streamlit can clear a placeholder, but:

- the user has already read the text, and
- the moment this is an HTTP API instead of a Streamlit page, **bytes on the wire cannot be
  recalled**.

Designing around "we'll overwrite it" builds a safety story that is true only for the current UI
framework — the exact coupling this project has refused everywhere else.

The honest statement:

> **Streaming trades enforceability for perceived latency.** A lookahead window can only catch
> what is decidable *within the window*. Anything requiring the whole answer cannot be blocked
> once streaming has begun — only flagged afterwards.

**Which points somewhere specific.** I wanted a future LLM policy judge to be able to halt the
stream. Two reasons it cannot:

1. **Cost.** A judge call per buffer means K extra round-trips on the critical path of the thing
   streaming exists to make fast. With a local 3B model that is hundreds of milliseconds each —
   time-to-first-token would end up *worse* than not streaming.
2. **Semantics.** "Does this answer comply with policy" is not a question you can ask of 40
   tokens without a large false-positive rate. It is inherently a whole-answer judgment.

> If a check genuinely requires whole-answer judgment, the place to stop a bad response is
> **before generation** — the input guardrails, which already exist. Output-side LLM judging
> belongs off the critical path: logged, sampled, and used to improve the prompt. Not a gate.

That is not a satisfying answer. It is the real one, and being able to say it is worth more in
an interview than a mechanism that pretends otherwise.

---

### Responsibilities After PR-12a

| Component | Owns | Explicitly does NOT own |
| --- | --- | --- |
| `_chain` | execution mode (`.stream()` / `.invoke()`) | buffering, guardrails, domain types |
| `stream_answer` | starting a stream; labelling sources once | flush timing, policy |
| `build_response` | the only `AIMessage → GenerationResponse` translation | when it is called |
| `_retrieve_context` | the guard→retrieve→guard prefix shared by both paths | generation, streaming |
| `_safe_flush_point` | where text may be cut without splitting a marker | when to flush, what to flush |
| `_stream_tokens` | buffering, flush timing, per-flush sanitizing, final assembly | how the model executes; how it looks |
| `strip_unverified_citations` | repairing invented markers in text | rejecting; domain objects |
| `typewriter` (`app.py`) | render cadence | content, order, safety |

The line that matters: **`GenerationService` owns how the model executes; `rag.py` owns when
text is allowed to reach the user.**

---

### Final Architecture

```
app.py
  stream = ask_stream(question, filters)     ← returns instantly, nothing generated yet
  st.write_stream(typewriter(stream.tokens)) ← consuming this starts the model
  response = stream.response                 ← readable only after the stream drains
        │
════════╪════════════════════════════════════════════════════════════════════
        ▼   rag.py — ORDER and TIMING
┌───────────────────────────────────────────────────────────────────────┐
│  _retrieve_context()                                                  │
│     validate_input ─┐                                                 │
│     retrieve        ├─ rejection? → tokens = empty, response = reject │
│     validate_context┘                                                 │
│                                                                       │
│  ┌── _stream_tokens() ───────────────────────────────────────────┐    │
│  │  for chunk in chunks:                                         │    │
│  │      accumulated += chunk       ← metadata rides here         │    │
│  │      pending     += chunk.content                             │    │
│  │                                                               │    │
│  │      if held < FLUSH_FLOOR:   continue        ← FLOOR         │    │
│  │      safe = _safe_flush_point(pending)        ← BOUNDARY      │    │
│  │      if safe == 0:            continue                        │    │
│  │                                                               │    │
│  │      yield strip_unverified_citations(pending[:safe]) ────────┼──→ UI
│  │                                                               │    │
│  │  ── end of stream ──                                          │    │
│  │  yield strip_unverified_citations(pending)    ← unconditional ┼──→ UI
│  │  response = build_response(accumulated, sources)              │    │
│  │  validate_output(response)   ← whole-answer validators, HERE  │    │
│  └───────────────────────────────────────────────────────────────┘    │
└───────────────────────────────────────────────────────────────────────┘
        │
════════╪════════════════════════════════════════════════════════════════════
        ▼   generation_service.py — EXECUTION MODE only
   stream_answer()  → (sources, chunk_iterator)    plain function, not a generator
   build_response() → GenerationResponse           the only AIMessage → domain mapping
        │
        ▼   the PR-10 chain — UNCHANGED
   RunnableParallel | prompt | llm       .stream() instead of .invoke()
```

The chain required **zero changes**. That is PR-10's claim paying out.

---

### Rejected Alternatives

| Alternative | Why rejected |
| --- | --- |
| `ask(..., stream=True)` | Two return types from one signature; callers must branch on the flag anyway |
| Yield token-by-token to the UI | Splits citation markers constantly; a guardrail pass per token |
| Verify citations chunk-by-chunk without a boundary rule | Makes the split-marker leak *rarer*, not gone — the worst possible outcome for a bug |
| Ceiling of `20 + x` tokens | The right instinct, but a guessed number. The grammar gives a defensible bound instead |
| Hold the entire buffer when a marker is in flight | Costs time-to-first-token and buys no extra safety over holding only the fragment |
| Mutable dict as an out-parameter for the final response | Invisible contract; the same class of bug as PR-11's Mistake 7 |
| Run all of `validate_output` per flush | `_check_empty_response` is meaningless on a partial answer — "was the answer empty" is only knowable at the end |
| Clear the screen when a validator rejects mid-stream | Only "works" in this UI; an HTTP API cannot un-send bytes. A safety story coupled to a framework |
| LLM policy judge per buffer | K extra round-trips on the critical path; makes TTFT worse than not streaming. Whole-answer judgment cannot gate a stream |
| Lower `FLUSH_FLOOR` to smooth the render | Fixes a presentation problem by shrinking a safety window |
| Buffering inside `GenerationService` | Buffering is sequencing policy; sequencing belongs to orchestration |

---

### What This PR Deliberately Did *Not* Change

- **The chain** — untouched. `.stream()` replaced `.invoke()` at the call site; nothing in the
  composition moved.
- **`ask()`** — retained, behaviour identical. It is the non-streaming peer, still the simplest
  way to test the pipeline without a UI.
- **Guardrail policy** — no rule changed. Only *when* sanitizing runs, and on what type.
- **`validate_output()`** — same signature, same call site, same order internally.
- **Prompts, `CitedSource`, retrieval, ingestion** — untouched.
- **Nothing new became a Runnable.** INVARIANT #1 holds: buffering, flush timing and guardrails
  are all plain Python.

---

### Mistakes I Made

#### Mistake 11 — Proposing chunk-by-chunk citation verification

I had already worked out in Week 3 that markers arrive split across chunks and must therefore be
resolved after the stream. Proposing per-chunk verification in this PR contradicted my own
recorded decision.

> **Lesson:** the danger was not the contradiction — it was that buffering would have *hidden*
> it. Large buffers make the split rare enough to pass casual testing and ship. A design that
> fails obviously is safer than one that fails occasionally.

#### Mistake 12 — Believing streamed output can be recalled

"Override it, or stop and replace it with a policy message." This felt reasonable because
Streamlit *can* clear a placeholder.

> **Lesson:** I was reasoning about my UI framework, not about the system. The test for any
> safety claim is whether it survives the transport changing. "Clear the div" does not survive
> becoming an HTTP response.

#### Mistake 13 — Not pricing the LLM judge

I proposed a helper LLM that could halt the stream mid-flight, without asking what it costs per
buffer.

> **Lesson:** any check placed on a critical path has to be priced in latency before it is
> designed. K judge calls to protect a feature whose entire purpose is reducing perceived
> latency is a design that undoes itself.

#### A correction I got right unprompted

Running the full `validate_output` per flush would have applied `_check_empty_response` to
partial text, where it is meaningless. Catching that before implementation is the
validator/sanitizer distinction from PR-11c doing exactly the work it was created for — the
first time that split has actually earned its keep.

---

### Production Failure Modes

- **A marker straddles a flush boundary.** Handled — `_safe_flush_point` holds the fragment.
  This is the failure the whole design exists to prevent.
- **An unmatched `[` that is ordinary text.** Handled — `MARKER_MAX` releases it after 8
  characters rather than stalling.
- **A marker at the very start of the buffer** (`safe == 0`). Handled — waits for more tokens.
  `MARKER_MAX` guarantees this cannot loop forever.
- **The model produces zero chunks.** Handled — `build_response(None, …)` yields an empty
  answer, which `_check_empty_response` then rejects. The failure is handled by its owner.
- **A validator rejects after tokens are shown.** *Not* handled, by design. The error appears
  below an answer the user has read. Documented as the cost of streaming, not papered over.
- **Ollama dies mid-stream.** Not handled — the generator raises inside `st.write_stream` and
  Streamlit shows a traceback. Same gap PR-10 logged, still owned by PR-15. Streaming makes it
  slightly worse: a partial answer is already on screen.
- **`response.answer` vs what the user saw.** `build_response` rebuilds the answer from the
  *raw* chunks, so it still contains markers that were stripped from the displayed text.
  `validate_output` re-runs the sanitizer over the whole answer, which reconciles them. That
  second pass is deliberate, not redundant.
- **Concurrency.** All streaming state — `pending`, `accumulated`, `held`, the handle — is local
  to one call. No module-level mutable state was introduced. PR-11's Mistake 7 did not recur.

---

### Engineering Lessons

1. **Streaming is a perceived-latency fix, not a throughput fix.** Total time is unchanged.
2. **`token → policy → screen`, never `token → screen`.** Policy cannot run over data already
   flushed.
3. **A framework giving you `.stream()` does not give you a streaming architecture.** The chain
   needed no changes; my own contracts needed all of them.
4. **Derive magic numbers from the structure they protect.** `MARKER_MAX` comes from the grammar
   of a citation, not from taste.
5. **A rare bug is worse than a constant one.** Buffering without a boundary rule would have
   made the split-marker leak ship.
6. **A generator function and a function returning a generator are different things.** One can
   only ever give you a single value.
7. **Expected outcomes belong in the return type; exceptions are for the unexpected.**
8. **Never weaken a safety mechanism to fix an appearance problem.** Different concerns, different
   layers.
9. **Price any check you put on a critical path** before designing it in.
10. **Streaming trades enforceability for perceived latency.** Hard blocks belong on the input
    side; output-side judgment is a flag, not a gate.
11. **When a design produces a special case, look for the framing where it stops being special.**
    A rejected request is just a stream with no tokens.

---

### Interview Takeaways

**What does streaming actually improve?**

> Perceived latency, not throughput. Total generation time is identical — the user just sees the
> first token in a few hundred milliseconds instead of waiting for the whole answer. If someone
> tells you streaming made their model faster, they measured the wrong thing.

**You already had LCEL. Wasn't `.stream()` free?**

> The chain genuinely needed zero changes — that was PR-10 paying out. What wasn't free was my
> own architecture. `ask()` returned a finished domain object, and every output guardrail assumed
> it ran before the user saw anything. Streaming inverts that ordering, and a framework can't fix
> an inverted ordering.

**How do you validate output you've already shown the user?**

> You mostly can't, and pretending otherwise is the mistake. I hold a lookahead window so policy
> runs before text is flushed, but a window only catches what's decidable *within* the window.
> Anything needing the whole answer can only be flagged afterwards. So hard blocks live on the
> input side, and output-side LLM judging goes off the critical path — logged and sampled, not a
> gate.

**Why not just stop the stream when a check fails?**

> Because "stop" doesn't undo what's already been read, and in an HTTP API the bytes are simply
> gone. Any safety story that depends on clearing a div is coupled to the UI framework. I'd rather
> state the trade-off honestly than build a mechanism that only appears to enforce something.

**How did you size the buffer?**

> Two numbers, and only one of them is a guess. The floor — how many chunks before a flush — is a
> UX judgment I tuned by feel. The ceiling is derived: a citation marker is `[` + digits + `]`, so
> with `TOP_K = 3` the longest is three characters. Past eight, an unmatched bracket can't be a
> marker, so I release it. That turns an unbounded wait into a bound I can defend.

**Why is the typewriter animation in the UI instead of just flushing smaller chunks?**

> Because they're different concerns. Buffer size is a safety parameter — it's the window my
> guardrails get. Render cadence is presentation. Smoothing the animation by shrinking the buffer
> would fix how it looks by degrading what it guarantees. Keeping them in separate layers makes
> that structurally impossible rather than a rule someone has to remember.

**Why is `ask_stream` a separate function instead of a flag on `ask`?**

> A flag would mean one signature returning either a response object or a generator, so every
> caller branches on the flag anyway — you've moved the branch, not removed it. Two peers with
> honest signatures, sharing an extracted prefix, costs four lines and reads correctly.

---

### Self-Check

Answer these without looking. If any is shaky, the corresponding section above is the fix.

1. What does streaming improve, and what does it leave exactly the same?
2. Which part of the streaming work was free because of PR-10, and which part was not?
3. Why can't `validate_output` reject once streaming has started?
4. Why does buffering *not* solve the split-citation-marker problem on its own?
5. Where does `MARKER_MAX = 8` come from? Why is that better than picking 20?
6. Why is a rare bug worse than a constant one here?
7. Why must `stream_answer` not contain a `yield`?
8. Why is a guardrail rejection a return value rather than an exception?
9. Why does a rejected request produce an *empty stream* rather than a special case in the UI?
10. Why is the typewriter animation in `app.py` and not in `rag.py`?
11. What breaks if someone "simplifies" `_safe_flush_point`?
12. Why can't an LLM policy judge gate a stream — give both reasons.

---

### Biggest Takeaway

> **The chain streamed for free. My contracts did not.**

PR-10 promised that adding streaming would not require editing orchestration code, and that
promise held exactly where it was made: the chain is untouched. What it could never have covered
is that my own design had a hidden assumption baked into it — that an answer arrives whole, so
everything after generation may inspect it before the user does.

Streaming did not break the framework integration. It broke an assumption, and the work of this
PR was finding where that assumption lived and deciding, one place at a time, what to do about
it.

The second lesson is about honesty in design. The most valuable output of this PR is not the
buffering code — it is the sentence *"streaming trades enforceability for perceived latency."*
I could have built something that looked like it enforced policy mid-stream. It would have
demoed fine and been wrong.

---

### A Note on Authorship

The design decisions in this document are mine, reached through discussion before any code
existed. The implementation of PR-12a was typed by an AI assistant from that design, at my
request, after I had committed to the architecture — the boundary rule, the layering, the
rejection of the mid-stream halt.

Recording that is deliberate. The defensible claim is *"I designed this and can explain every
trade-off in it,"* not *"I typed every character."* Only the first one survives an interview
anyway.

---

**Next:** PR-12 — Chat History, and the concept is **state management**. The first defect is
already visible: the answer you just watched stream in will vanish the moment you touch any
other widget on the page.

---
---

## PR-12 Discussion — State Management *(in brief)*

Most of this PR is `app.py`, and UI plumbing does not deserve a long write-up. Three decisions
in it are not about UI at all, and those are the ones worth keeping.

### The Problem — Values in the Wrong Band

The answer lived in a local variable inside `if st.button("Ask")`. Streamlit reruns the whole
script on *any* widget interaction, so changing the document filter destroyed an answer an LLM
call had just been paid for.

That framing — "the answer disappears" — is the symptom. The cause is that this application had
**three distinct kinds of state and treated them as one thing**:

```
┌─ transient ──────────┐  dies at end of run     the streamed answer, filters
├─ session ────────────┤  per user, in RAM       conversation history
└─ persistent / disk ──┘  all users, survives    storage/*.index, metadata_catalog.json
```

Every defect in this PR was a value sitting in the wrong band.

### Design Decision #21 — Derive, Don't Store

The sidebar reports accumulated conversation cost. The obvious implementation is a running
counter incremented per turn. It is recomputed from the turn list instead, on every run.

A counter would be a **second copy of a fact the turn list already holds**, and the two would
disagree the first time history was cleared. Recomputing over a handful of turns is free;
keeping two sources of truth in sync never is.

The payoff shows up somewhere unexpected: "Clear Conversation" is a single assignment. Had
totals been stored separately, that button would have needed to remember to reset them too —
and one day it would have forgotten.

> **Engineering Principle**
> Prefer deriving to storing. A stored aggregate is a synchronization obligation you take on
> forever, in exchange for arithmetic you were not struggling with.

### Design Decision #22 — The Page Is a Function of State

The first version appended the new turn to history at the bottom of the script, and the sidebar
totals never updated — because the sidebar had rendered near the *top*, before the state changed.
Nothing recomputed them, because nothing re-executed.

The fix is one line, `st.rerun()` after the append, but the rule it enforces is the entire PR:

> **THE PAGE IS A FUNCTION OF STATE.**
> Anything rendered before the state changed is stale by definition.

This is also what makes the replay loop correct. History renders from session state on every
run; only the newest reply is animated. The transition from "being streamed" to "history" *is*
the transition from transient state to session state, made visible.

### The Overstatement I Had to Withdraw

I described the upload panel not rendering in a fresh session as *"two sources of truth — two
parts of the app disagree."* On re-examination that was too strong, and the correction matters
more than the original claim.

No data was wrong. Nothing returned an incorrect answer. The panel is legitimately an upload
**receipt** — its own expander says *"Chunks Indexed This Upload"* — and a receipt disappearing
when you leave is correct behaviour.

The real, much narrower issue: two of its four metrics (*Knowledge Base Size*, *Vocabulary
Size*) are **corpus** facts trapped inside an upload-scoped branch, so a returning user saw an
empty uploader while the chat below answered from a fully built index.

> **Engineering Principle**
> Scope each displayed fact to its own lifetime. "How long did this upload take" and "how big is
> my corpus" have different lifetimes; rendering them in one block ties the second's visibility
> to the first's.

Fixed by reading `MetadataCatalog.list_documents()` once at the top of the page and rendering it
outside the session-state branch — with the retrieval filters reusing the same list, so the two
panels are *structurally incapable* of disagreeing rather than merely currently agreeing.

### A Return Value That Outlived Its Reason

`ingest_documents` returned the raw embeddings, and `app.py` cached them in session state and
never read them. Measured: **~24.8 KB per chunk** as `list[list[float]]`, so ~24 MB per 1000
chunks held in per-session RAM for nothing.

Tracing it explains how it survived. The vectors are *consumed* at `vector_store.store()` — from
that line, the FAISS index on disk **is** the embeddings, in a form built for searching. They
were returned alongside `dimension` and `elapsed` back in PR-4, when the UI showed embedding
stats and persistence did not exist yet. PR-5 added FAISS and made them redundant. The return
signature was never revisited.

> Nobody removed it because nothing broke. That is exactly why this kind of thing survives.

Removed from the chain, not just from session state — `app.py` caching it was the symptom;
returning a consumed value was the defect.

---
---

## PR-13 Discussion — Conversation Memory

### Problem Statement

PR-12 made the *application* remember. **The pipeline still did not.** `ask_stream()` treated
every question as though it were the first one ever asked.

```
You: Tell me about Ayanabha
Bot: Ayanabha Misra is a Front-end Developer… [2][3]

You: What are his skills?
```

The second query contains no name, no topic, nothing distinctive. It gets embedded as-is, and
BM25 scores it on *what*, *are*, *his*, *skills*. Three unrelated chunks come back, and a
confident answer is built on them.

The trap in this problem is that it looks like one problem and is two. A question has **two
consumers**, and they need different things:

```
"What are his skills?"
        │
        ├──→ the RETRIEVER    embeds it, BM25-scores it
        │                     needs: something that stands alone
        │
        └──→ the LLM          reads it alongside <context>
                              needs: to know who "his" refers to
```

> **The engineering problem is not "the model has no memory."**
> It is: *the retriever runs before the prompt exists, so anything given to the model arrives
> too late to affect what was fetched.*

---

### Core Thoughts — What I Believed Going In

My first design was: have the generation LLM emit a short summary of the conversation alongside
its answer, and inject that summary into the next prompt as a `<history>` tag beside `<context>`.

Two things about that are right, and I kept both:

- A **bounded** summary cannot outgrow the context window — no eviction policy needed.
- A **citation-free** summary dissolves the request-scoped-label conflict rather than patching it.

What it misses is the entire retrieval half. Feed the summary only to the model and the retriever
still runs on `"what are his skills?"`. Then one of two things happens, and the second is worse:

1. The model obeys Rule 2 and replies *"I cannot find the answer in the provided documents."*
   The feature does not work.
2. The model answers from the `<history>` tag, because that text is right there and looks
   relevant. Now the answer is grounded in a summary rather than in retrieved evidence, **with no
   citable source.** That is not a RAG system anymore.

> Getting the answer to *read* well and getting the retrieval to *be* right are separate
> problems. Solving the first and shipping the second broken demos beautifully.

---

### Design Decision #23 — Summarize, Don't Replay

The textbook approach is to pass the last N turns verbatim. Rejected for three reasons that
compound:

| Replaying raw turns | Cost |
| --- | --- |
| Unbounded growth | Needs an eviction policy, and every eviction rule silently discards something a later question might need |
| Carries citation markers | `[2]` means `01-vision.md` in turn one and `Resume.pdf` in turn three. Request-scoped labels leaking into a cross-turn artifact is precisely the failure `CitedSource`'s materialized mapping exists to prevent (PR-11, DD #9) |
| Carries retrieved context | Old `<context>` blocks would dominate the window and confuse attribution |

A rolling summary makes all three go away **by construction** rather than by rule: three
sentences cannot grow, and a prompt rule forbidding markers means there is nothing to strip.

The technique has a name — **rolling / progressive summarization**. Its known weakness is worth
recording: turn 10's summary is summarized from turn 9's, which came from turn 8's. It is a
tenth-generation copy, and detail degrades. Production systems usually keep the last N turns
verbatim *alongside* a summary of everything older. Not built here; noted as the next move if
fidelity becomes the complaint.

---

### Design Decision #24 — The Summary Feeds Both Consumers

This is the correction that turned a half-design into a design.

```
summary ──┬──→ retrieval query   =  summary + "\n" + question
          │
          └──→ <history> block in the generation prompt
```

One artifact, two uses. The retrieval half is what makes the feature actually work; the
generation half is what makes the answer read naturally. Feeding only the second is the
seductive version, because it demos fine on questions the summary happens to cover.

---

### Design Decision #25 — A Separate Call, Deferred Behind the Stream

My original design bundled summary generation into the answer call. Rejected on three
independent grounds:

1. **It fights streaming.** The answer streams token by token. A summary emitted by the same
   call streams into the user's view, and stripping it mid-stream is the split-marker problem
   again — spanning a whole block instead of three characters.
2. **It asks for structured output.** PR-11 Design Decision #8 already concluded this model is
   not reliable at JSON. That conclusion did not stop being true.
3. **Two responsibilities, one call.** Answering and summarizing have different failure modes,
   and a failure in either corrupts the other.

The saving it appeared to buy — *"no second LLM call"* — was illusory. The second call was not
removed, it was hidden inside the first one where it could damage the answer.

**So the real question became: where does a second call go without costing time-to-first-token?**

```
TURN N-1                                    TURN N
  … stream answer …                           summary already exists  ← free
  ▶ last token flushed                        validate_input
  ─────────── critical path ends ───────      retrieve(summary + question)
  SummarizationService.summarize(…)           stream answer
  sanitize → validate → accept                ▶ first token
```

The summary produced after turn N−1 is the one turn N consumes. **The read path never generates
the summary it uses.**

> **Engineering Principle**
> Move work from read time to write time. Conversation memory is not free — it is a whole extra
> LLM call — but it is paid where nobody is waiting.

That is the same trade a materialized view makes: pay once when the data changes, so every read
is cheap.

**Precision that matters: this is deferred, not asynchronous.** Streamlit is synchronous and
single-threaded per session; a real thread has no `ScriptRunContext` and cannot safely touch
`st.session_state`. Calling this "running in the background" would be a lie about the mechanism.
What is true, and what matters, is that it is *off the critical path of every question*.

---

### Design Decision #26 — Concatenate, Don't Fuse

`fusion_service.py` already does Reciprocal Rank Fusion over multiple result lists. So the
tempting design is: retrieve once on the question, once on the summary, and fuse.

It is wrong, and the reason is the interesting part.

> **RRF assumes its inputs are comparably-competent rankings of the same information need.**

Dense and sparse retrieval over one query satisfy that. Question-only and summary+question do
not — on a follow-up, the question-only arm is *known* to be noise. And because RRF scores by
reciprocal rank, a junk chunk ranked #1 in the bad arm scores about the same as a good chunk
ranked #1 in the good arm. The result is not mild dilution; it is **noise promoted into the
top-K at near-equal weight**. Strictly worse than not fusing at all.

Chosen instead:

```python
def _build_retrieval_query(summary, query):
    if not summary:
        return query
    return f"{summary}\n{query}"
```

> **Engineering Principle**
> Knowing when *not* to reach for a component you already own is worth more than reaching for it.
> A pattern applied outside its assumptions does damage in the shape of the assumption it broke.

---

### Design Decision #27 — Guardrails Split by Consequence, Not by Direction

The summary is model output, generated from documents nobody controls, and it is injected into
every later prompt. That makes it the one piece of model output that **outlives its request** —
so a poisoned summary persists across turns instead of dying with one.

My first instinct was to run `validate_input(summary + query)`. That has two concrete bugs:

**Bug 1 — the empty check stops working.** `_check_empty_query` is `if not query.strip()`. From
turn 2 onward `summary + ""` is never empty, so a blank question sails into retrieval.

**Bug 2 — it blames the user for the machine's contamination.** A poisoned summary would reject
a perfectly innocent question, with a message the user cannot act on, and would keep doing so on
every subsequent question. A permanently wedged session.

Both come from one mistake: **one function, two inputs with different trust levels and different
correct consequences.**

| Input | Trust | Correct consequence |
| --- | --- | --- |
| the user's question | untrusted human input | **reject** — they can rephrase |
| the conversation summary | contaminated machine state | **discard the summary** — the user did nothing wrong |

The second row is PR-11c's sanitize-don't-reject decision recurring in a new place: *a wrong
attribution doesn't make the answer wrong*, and here, *a poisoned memory doesn't make the
question bad.*

**Which forced a third module.** Both directions need the identical injection check. Duplicating
six keywords across `input_guardrails.py` and `output_guardrails.py` means adding a phrase to one
and forgetting the other — a drift bug with a security consequence rather than a cosmetic one.

```python
# guardrails/text_policy.py
def contains_injection_attempt(text: str | None) -> bool:
```

The naming is the design. This is not "input policy" or "output policy" — it answers one
question with no direction: *does this text contain something shaped like an instruction?* It
returns a **bool**, never a domain object, because a function that decided the consequence could
only ever serve one of its two callers.

> **Engineering Principle**
> Extract the *question*, not the *answer*. Shared logic that also decides what to do about
> itself is not shareable.

**When a summary fails:** keep the previous one. Memory stops advancing rather than vanishing —
the conversation retains what it already knew and the user sees nothing go wrong. Clearing it
instead would turn one bad summary into sudden amnesia mid-conversation.

---

### Design Decision #28 — Where the Summary Lives

Two placement questions, and both have a wrong answer that looks reasonable.

**Not on `GenerationResponse`.** Three reasons:

1. **Wrong lifetime.** `GenerationResponse` is *the answer to one question*. A summary describes
   *the whole conversation*.
2. **The rejection path makes it meaningless.** Guardrails return `GenerationResponse` objects
   when they refuse. A summary field would be required-looking and meaningless on half the
   objects that type produces.
3. **Wrong timing.** Summarization runs *after* the stream, when the response is already built.
   It would have to be mutated late.

It lives on `StreamedAnswer` instead — the object that already means *"everything this call
produced"*, already has fields filled at different times, and already has a documented
consumption contract.

```python
@dataclass
class StreamedAnswer:
    tokens: Iterator[str]
    response: GenerationResponse | None = None
    summary: str | None = None              # PR-13
    summary_token_usage: dict | None = None # PR-13
```

`summary` is **seeded with the incoming summary**, so every path that does not produce an
accepted new one — a guardrail rejection, a failed validation — leaves the caller's memory
untouched rather than wiping it. The caller's assignment becomes a harmless no-op instead of a
special case it has to remember to skip.

**Not one per turn.** There is exactly *one* current summary. Storing a copy on each `ChatTurn`
would make "the current one" mean "whichever is in the last element" — meaning implied by list
position, which is precisely the fragility rejected in PR-11 DD #9 when positional citation
markers lost to a materialized mapping. It is a single key: `st.session_state.conversation_summary`.

---

### Design Decision #29 — Two Costs, Two Fields

Every turn is now two LLM calls. The sidebar says *"Conversation cost."* Folding the summary
call's tokens into `response.token_usage` would make the per-turn "Prompt Tokens" metric describe
two different calls at once — and reporting only the answer's tokens would understate the real
spend by roughly half.

Either way the instrumentation lies, and PR-11 already recorded why that is the worse failure:

> Missing data makes you go and find it. **Misleading data makes you build on it.**

So: `ChatTurn.summary_token_usage`, reported separately as **context upkeep**. Keeping memory is
a real cost — but it is the cost of maintaining *context*, not the cost of answering a question,
and the two sitting side by side is the honest picture of what conversation memory is worth.

---

### Rule 6 — Memory Resolves References, It Does Not Supply Facts

The `<history>` block creates a new way for the system to be wrong: the model can answer *from
memory* instead of from retrieved evidence, producing a fluent, confident, **uncitable** answer.

```
6. The <history> block is a summary of earlier turns in this conversation. Use it ONLY to
   understand what the question refers to — for example, who "he" or "it" means. It is not a
   search result. Never state a fact that appears only in <history>, and never cite it. Every
   fact in your answer must come from <context>.
```

The block sits **first** in the human message, because it frames the question that follows — and
**in the human message, never the system message**, by the same reasoning as PR-10 DD #5: it was
written by a model reading documents we do not control, so it belongs where data lives, not
where policy lives. Rule 6 is the policy *about* it; the block itself is quoted material.

This is a prompt-compliance guarantee, not a hard one. It is the weakest link in the PR, and
saying so is more useful than pretending otherwise.

---

### Responsibilities After PR-13

| Component | Owns | Explicitly does NOT own |
| --- | --- | --- |
| `SummarizationService` | producing a summary from (previous summary, Q, A) | when it runs, whether it is safe to use |
| `text_policy.contains_injection_attempt` | the *question* "is this instruction-shaped?" | the consequence |
| `validate_summary` | whether a summary is fit to inject | producing one, storing one |
| `sanitize_summary` | stripping request-scoped markers out of a cross-turn artifact | judging |
| `_build_retrieval_query` | what retrieval actually searches on | retrieval strategy |
| `_refresh_summary` | sequencing sanitize → validate → accept | generating, storing |
| `rag.py` | order, and deferring the write path behind the stream | prompt text, summary content |
| `GenerationService` | rendering `<history>` into the prompt | what history *is* |
| `StreamedAnswer` | carrying the new summary out | storing it |
| `app.py` | holding the one current summary; clearing it with the conversation | generating or validating it |
| `GenerationResponse` | *(unchanged)* the answer to one question | anything conversational |

---

### Final Architecture

```
app.py
   summary = st.session_state.conversation_summary       ← produced last turn
        │
        ▼
rag.ask_stream(question, filters, summary) ──→ StreamedAnswer(summary=summary)
        │
        │  ┌─ READ PATH — on the critical path ─────────────────────────┐
        │  │  validate_input(question)         ← RAW question ONLY      │
        │  │  retrieve(summary + "\n" + question, TOP_K, filters)       │
        │  │  validate_context(question, documents)                     │
        │  │  stream_answer(question, documents, summary)               │
        │  │      human: <history> … <context> … Question: …            │
        │  │  ▶ tokens flush to UI                                      │
        │  │  build_response → validate_output                          │
        │  └────────────────────────────────────────────────────────────┘
        │
        │  ┌─ WRITE PATH — deferred, after the last token ──────────────┐
        │  │  if response.success:                                      │
        │  │      candidate, usage = SummarizationService.summarize(…)  │
        │  │      candidate = sanitize_summary(candidate)               │
        │  │      if validate_summary(candidate):                       │
        │  │          handle.summary = candidate                        │
        │  │      # else: keeps the seeded previous summary             │
        │  └────────────────────────────────────────────────────────────┘
        ▼
app.py
   st.session_state.conversation_summary = stream.summary   ← one value, replaced
```

Only **successful** turns are summarized. A guardrail rejection has no answer worth remembering,
and folding *"the user asked something we refused"* into memory would carry the refusal forward
into every later prompt.

---

### Rejected Alternatives

| Alternative | Why rejected |
| --- | --- |
| Replay the last N turns verbatim | Unbounded; carries request-scoped citation markers into a cross-turn artifact; needs an eviction policy |
| Summary emitted by the answer call | Puts summary text in the user's token stream; demands structured output from a 3B model; two responsibilities in one call |
| Summary fed only to the LLM | Retrieval still runs on the bare question. Model then answers from `<history>` — fluent, confident, **uncitable** |
| An LLM query-rewrite before retrieval | Correct, but it sits *between* the question and the first token — spending back exactly what PR-12a bought |
| Retrieve twice (question, summary) and fuse with RRF | RRF assumes comparably-competent rankings of one information need; the question-only arm is known noise, and reciprocal-rank scoring promotes it into the top-K |
| `validate_input(summary + query)` | Breaks the empty-question check from turn 2 onward; rejects the user for machine contamination they cannot fix, wedging the session |
| Duplicate the injection regex in both guardrail modules | Drift bug with a security consequence |
| A shared checker that returns `GenerationResponse` | Would decide the consequence, and the two callers need *different* consequences |
| Summary on `GenerationResponse` | Wrong lifetime; meaningless on rejection objects; would need late mutation |
| A summary copy on every `ChatTurn` | "Current" would mean "last element" — positional meaning, rejected in PR-11 DD #9 |
| Summary tokens folded into `response.token_usage` | Makes a per-turn metric describe two different calls |
| Clear the summary when validation fails | Turns one bad summary into sudden amnesia; keeping the previous one degrades instead |
| Threading for "background" summarization | Streamlit threads have no `ScriptRunContext` and cannot safely touch session state |

---

### What This PR Deliberately Did *Not* Change

- **The streaming machinery** — `_safe_flush_point`, `FLUSH_FLOOR`, `MARKER_MAX`, the typewriter.
  Untouched. PR-13 adds a step before and a step after; the middle is exactly PR-12a's.
- **`validate_output()`** — same signature, same call site, same internal order. The two new
  summary functions sit beside it, not inside it.
- **`GenerationResponse`** — not one new field.
- **Retrieval strategy** — `RetrievalService`, RRF, metadata filtering all unchanged. Only the
  *string* handed to them changed.
- **`ask()`** — accepts a summary for parity but does **not** produce one. A caller with no
  stream to defer behind would pay for summarization synchronously, and that path exists for
  testing the pipeline without a UI.
- **`CitedSource`, ingestion, prompts' rules 1–5** — untouched.
- **Nothing new became a Runnable.** INVARIANT #1 still holds.

---

### Known Limitation — Topic Change

Accepted deliberately, documented rather than hidden.

The summary is three sentences; the question is a handful of words. In the concatenated retrieval
query the summary dominates both the embedding and the BM25 term counts. That is exactly what a
follow-up needs — and exactly wrong when the user changes subject:

```
turns 1–3   Ayanabha's resume
turn 4      "what is reciprocal rank fusion?"

retrieval query = [3 sentences about a front-end developer] + "what is reciprocal rank fusion?"
```

Resume chunks come back for a question about RRF. Clearing the conversation resets it, but
requiring the user to know that is not a fix.

**Why it was not solved here.** The fix is cheap — embed the question, cosine-compare it against
the summary, drop the summary below a threshold; the question's vector is computed for the dense
arm anyway. What it is not is *free*: it introduces a magic threshold with no data to tune it on,
and it would make PR-13 teach two concepts instead of one.

> A stated limitation reads as judgment. An unstated one reads as an oversight.

---

### Mistakes I Made

#### Mistake 14 — Solving the half of the problem that shows

My first design gave the summary to the model and left retrieval untouched. It felt complete
because the *symptom* I had reproduced was "the model doesn't know who 'he' is."

> **Lesson:** when a problem has two consumers, the one you can see is not necessarily the one
> that matters. The retriever runs before the prompt exists, so it was invisible in every mental
> trace I ran — and it was the half that made the feature actually work.

The failure mode this would have shipped is the instructive part: not a crash, not a refusal, but
a fluent answer built on the summary rather than on evidence, with nothing to cite. It would have
demoed perfectly.

#### Mistake 15 — Saying "background" about a synchronous framework

I designed the summary call to "run in the background so it doesn't block the front end." The
*intent* was right and survived into the final design. The *word* was wrong: Streamlit is
synchronous and single-threaded per session, and a real thread has no `ScriptRunContext`.

> **Lesson:** describing a mechanism you have not verified is how a good design acquires a claim
> it cannot support. "Off the critical path" is true, precise, and just as impressive. "In the
> background" would have been a bad thirty seconds in an interview.

#### Mistake 16 — One guardrail for two trust levels

`validate_input(summary + query)` looked like defense in depth. It was two bugs: a broken
empty-question check, and a permanently wedged session blaming the user for the machine's
contamination.

> **Lesson:** the question *"is this text dangerous?"* is shared. The answer *"so reject the
> request"* is not. Bundling the question with the answer is what made a reusable check
> unreusable.

---

### Production Failure Modes

- **The model answers from `<history>` instead of `<context>`.** Mitigated by Rule 6 only —
  prompt compliance, not a guarantee. The visible symptom is a fluent follow-up answer carrying
  **no citations**. Watch for it; it is a prompt problem, not a code problem.
- **The summary is poisoned by a retrieved chunk.** Handled — `validate_summary` rejects it and
  the previous summary is kept.
- **A citation marker leaks into the summary.** Handled — `sanitize_summary` strips it before
  validation, so a request-scoped label can never become a cross-turn artifact.
- **The user changes topic.** *Not* handled. Documented above.
- **Summary quality degrades over a long conversation.** Expected — each summary is derived from
  the previous one. Bounded but real. The mitigation, if it becomes a complaint, is keeping the
  last N turns verbatim alongside the summary.
- **The summary call fails (Ollama down) after the answer streamed.** Not handled — it raises
  after the user already has their answer, so Streamlit shows a traceback *below* a correct
  reply. Slightly worse than PR-12a's version of the same gap. Still PR-15's.
- **Concurrency.** No new module-level mutable state. The summary is passed in as a parameter and
  returned on a per-call handle.

---

### Engineering Lessons

1. **A problem with two consumers is two problems.** Solving the visible one ships the other
   broken.
2. **Move work from read time to write time.** Memory costs a whole extra LLM call; it just does
   not have to be paid where someone is waiting.
3. **Deferred is not asynchronous.** Know which one you built, and say that one.
4. **Bounded by construction beats bounded by rule.** Three sentences cannot outgrow a window; an
   eviction policy is a rule someone has to get right forever.
5. **Extract the question, not the answer.** Shared logic that decides its own consequence serves
   exactly one caller.
6. **Split guardrails by consequence, not by direction.** Same check, different trust level,
   different correct outcome.
7. **Knowing when not to use a component you own** is worth more than using it.
8. **Seed the output with the input** when a step may legitimately produce nothing — it turns a
   special case into a no-op.
9. **Two costs deserve two fields.** An aggregate that hides half the spend is worse than no
   aggregate.
10. **A stated limitation is judgment; an unstated one is an oversight.**

---

### Interview Takeaways

**How does a RAG system handle follow-up questions?**

> The naive answer is "put the chat history in the prompt", and it's half right. The retriever
> runs *before* the prompt is built, so history given to the model arrives too late to change
> what was fetched. A question has two consumers with different needs — the retriever needs
> something self-contained, the model needs to resolve references. I maintain one rolling summary
> and feed it to both: prepended to the retrieval query, and injected as a delimited `<history>`
> block in the prompt.

**Doesn't that cost you the time-to-first-token you spent a whole PR buying?**

> Not if you put it in the right place. The summary a turn consumes was produced at the end of
> the *previous* turn, after the last token was flushed, while the user was reading. It's the
> same trade a materialized view makes — pay when the data changes so every read is cheap. I'd be
> careful with the word "background" though: Streamlit is synchronous, so it's deferred, not
> asynchronous.

**Why summarize instead of keeping the turns?**

> Three problems collapse into one decision. Raw turns grow unbounded, so you need an eviction
> policy. They carry citation markers, and my markers are request-scoped — `[2]` means a different
> document each turn, so replaying them corrupts attribution. And they carry old retrieved context
> that would dominate the window. A three-sentence citation-free summary makes all three
> impossible by construction rather than by rule.

**You had RRF already. Why not retrieve on both and fuse?**

> RRF assumes its inputs are comparably-competent rankings of the same information need. On a
> follow-up, the question-only arm is known to be noise — and RRF scores by reciprocal rank, so a
> junk chunk at rank 1 in the bad arm scores about the same as a good chunk at rank 1 in the good
> arm. I'd be promoting noise into the top-K at near-equal weight. Fusion is for two good
> retrievers, not one good and one broken.

**The summary comes from your own model reading untrusted documents. How do you handle that?**

> It's the only model output in the system that outlives its request, so it's the one worth
> checking twice. I don't run it through the input guardrail though — that would break the
> empty-question check and would reject an innocent question because of contamination the user
> can't see or fix, wedging the session. The check itself is shared, in its own module, returning
> a bool; the two callers decide different consequences. Reject the user's question, but *discard*
> a bad summary and keep the previous one. Memory stops advancing instead of disappearing.

**What does conversation memory cost?**

> Roughly double the LLM calls, and I report it as a separate line rather than folding it into the
> answer's token count — that metric is the cost of answering one question, and merging them would
> hide about half the spend inside a number labelled something else.

**What breaks in your design?**

> Topic change. The summary is three sentences and the question is a few words, so in the
> concatenated retrieval query the summary dominates. Ask about something new on turn four and
> you retrieve chunks about turns one to three. The fix is cheap — cosine-compare the question
> against the summary and drop it below a threshold — but it needs a magic number I have no data
> to tune, so I documented it rather than guessing.

---

### Self-Check

1. Why does giving chat history to the model not fix follow-up questions?
2. What are the two consumers of a question, and what does each need?
3. Name the three problems a rolling summary removes *by construction*.
4. Why is the summary call after the stream rather than before retrieval?
5. What is the difference between "deferred" and "asynchronous", and which did you build?
6. Why can't you fuse question-only and summary+question results with RRF?
7. What two bugs does `validate_input(summary + query)` introduce?
8. Why does `contains_injection_attempt` return a bool instead of a `GenerationResponse`?
9. Why does a failed summary keep the previous one instead of clearing?
10. Why is the summary on `StreamedAnswer` and not on `GenerationResponse`?
11. Why is there one summary key rather than a summary per `ChatTurn`?
12. What does Rule 6 forbid, and what is the visible symptom when the model ignores it?
13. When does this design fail, and what would fixing it cost?

---

### Biggest Takeaway

> **Memory is not a feature you add to the model. It is an artifact you maintain between turns.**

Every wrong version of this PR treated memory as something handed to the LLM at generation time.
That framing produces a system that *sounds* like it remembers and *retrieves* like it does not —
and the failure mode is an answer that is fluent, confident, and cannot be cited.

The version that works treats the summary as a small piece of maintained state with its own
lifecycle: produced off the critical path, sanitized, validated, stored in exactly one place,
consumed by two different components for two different reasons, and discarded as a unit when the
conversation is cleared.

The second lesson is about where cost goes. Conversation memory is not cheap — it doubles the LLM
calls. What made it feel free was noticing that the expensive part does not have to happen
between a question and its answer.

---

### A Note on Authorship

As with PR-12a: the design decisions here are mine, reached through discussion before any code
existed — including the ones I got wrong first and had to abandon, which are recorded above as
Mistakes 14 to 16. The implementation of PR-12, PR-12a, and PR-13 was typed by an AI assistant
from those designs, after I had committed to the architecture.

The defensible claim is *"I designed this and can explain every trade-off in it"* — which is the
only claim that survives being questioned anyway.

---

**Next:** PR-14a — Configuration. `TOP_K = 3` is a module constant, model names are hardcoded,
and `FLUSH_FLOOR`, `MARKER_MAX`, and now the summary's sentence cap have joined them. Every one
of those is a value someone may need to change without a redeploy.
