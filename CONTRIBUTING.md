# Contributing

Read this first, because this repository is probably not what you expect.

**This is a learning archive, not a maintained product.** It was built over four weeks as a
public record of *how* a RAG application gets designed — one engineering concept per pull
request, with every decision and every rejected alternative written down in
[`docs/engineering-mindset/`](docs/engineering-mindset/).

The commit history is the point. A pull request that improves the code but flattens the
sequence of reasoning removes the thing this repo exists for.

---

## The most useful thing you can do

**Disagree with a decision.** Open an issue.

Every non-obvious choice here has a written argument behind it, which means every one of them
can be argued with. Some examples that are genuinely open:

- Fusing question-only and summary-prefixed retrieval was rejected because RRF assumes
  comparably-competent rankings. Is that right?
- `MARKER_MAX` is derived from `TOP_K` rather than configured. Too clever?
- Conversation memory is a rolling summary rather than the last N turns verbatim, which
  degrades over long conversations. Where does that break first?
- Output-side LLM judging is deliberately off the critical path. Is there a design where it
  can gate a stream without destroying time-to-first-token?

An issue that says *"your reasoning in Design Decision #26 breaks when X"* is worth more here
than a patch. If you're right, the doc changes and so does the code.

---

## If you want to open a pull request

Fine, with two asks:

1. **One concept per PR.** This is the rule the whole repo was built under. A PR that fixes a
   bug *and* renames things *and* adds a feature can't be reviewed for any of them.
2. **Say what you rejected.** The interesting half of a design is the alternatives you
   considered and dropped. Every PR description here does that; yours should too.

Bug fixes and factual corrections in the docs are always welcome and need none of the above
ceremony.

---

## If you want to learn from it

That's the intended use. Two suggestions:

**Read the docs before the code.** `docs/engineering-mindset/week-3-AI-Assistant.md` and
`week-4-AI-Assistant.md` explain *why* each piece looks the way it does. The code without them
is just another RAG app.

**Read the "Mistakes I Made" sections.** They are the honest record of designs that were wrong
first — a summary that fed only the model and left retrieval broken, a thread id used as a
request id, retention implemented by rewriting a whole file. Those are more instructive than
the parts that worked.

Fork it and rebuild it yourself if you want the learning to stick. Following the PR sequence in
[`PR-Journey.md`](PR-Journey.md) from an empty directory is the way it was meant to be used.

---

## Running it locally

Setup is in the [README](README.md). There is no test suite — this project was verified by
inspection, targeted scripts, and running the app, which is stated plainly rather than hidden
behind a badge. If you add tests, that's a genuinely welcome PR.

## Code style

Match the file you are editing. Two conventions worth knowing:

- **Comments explain *why*, not *what*.** The codebase is unusually heavily commented on
  purpose, because the reasoning is the deliverable.
- **Framework code stays in one place.** Guardrails, retrieval, buffering, and memory are plain
  Python with no LangChain imports. Only prompt-to-model composition is declarative. Please
  don't blur that line without arguing for it first.
