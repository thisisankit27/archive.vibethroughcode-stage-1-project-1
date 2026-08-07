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
