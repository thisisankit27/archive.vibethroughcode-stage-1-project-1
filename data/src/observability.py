"""Observability plumbing: one logger, two destinations.

WHY THIS EXISTS

"The answers got worse" is unanswerable today. Retrieval could have returned bad chunks, the
summary could have dragged the query off-topic, the model could have cited nothing and
answered from memory, or the question could just have been harder. Each has a different fix
and nothing distinguishes them.

The instrumented list is not generic - it is the blind spots already recorded across PR-10 to
PR-13:

    prompt silently drops {context}      fluent answers built on nothing, no exception
    model answers from <history>         an answer with NO citation markers
    topic change drags retrieval         wrong chunks, plausible answer
    no relevance floor on TOP_K          an irrelevant chunk in every result set
    an invented citation is stripped     a quality signal that was being discarded
    a summary is rejected                memory silently stops advancing

The last two are the point. Every sanitizer is a quality sensor nobody was reading.

WHAT GETS LOGGED

Decisions and their reasons - shapes, counts, verdicts, identifiers. NOT inputs and outputs.
Logging the input to strip_unverified_citations means logging the whole answer; logging the
input to _render_sources means logging every retrieved chunk. This app runs over documents
somebody uploaded, and the file sink is DURABLE - it outlives the session and can be copied
somewhere the reader never saw those documents.

    BAD   stripped citations: input="Reciprocal Rank Fusion scores each document by [2][3]…"
    GOOD  citations.stripped  removed=1  invalid=['4']  issued=['1','2','3']

Same diagnostic fact, no user content, and the second one is countable.

TWO DESTINATIONS, ONE CALL SITE

Services call plain `logger.info(...)`. Two handlers decide where it goes:

    TraceHandler             -> the current turn's list -> StreamedAnswer.trace -> UI panel
    TimedRotatingFileHandler -> storage/app.log, rotated at midnight, 7 kept

A bespoke event collector would have meant writing the fan-out twice. Using stdlib `logging`
also means PR-16 gets a stdout handler for free without touching a single service again.

WHY A ContextVar AND NOT threading.local()

Both give ambient state at any call depth without polluting signatures. ContextVar is the one
that is still correct later:

  - threads are REUSED (Streamlit runs a session's reruns on the same ScriptRunner thread), so
    thread-local state leaks from one turn into the next unless you remember to clear it, and
    forgetting is silent - you get the previous turn's trace, which looks correct
  - `.set()` returns a token and `.reset(token)` restores the previous value, so scoping nests
    and cannot leak
  - async is many coroutines on ONE thread; they would all share a single thread-local and
    overwrite each other. LCEL hands you .astream() for free, so this is a real future

Note what the ContextVar holds: not a request ID, but the COLLECTOR ITSELF. There is no
correlation problem to solve because events were never mixed - each turn's events go into that
turn's list. An ID would only be needed if everything landed in one stream and had to be
sorted out afterwards.
"""

import logging
import time
from contextvars import ContextVar
from logging.handlers import TimedRotatingFileHandler

from data.src.config import LOG_FILE, LOG_LEVEL, LOG_RETENTION_DAYS

# The current turn's event list. None outside a turn - logging still works, it just has no
# trace to append to (e.g. the ingestion pipeline, which is not part of a question).
_current_trace: ContextVar[list | None] = ContextVar("current_trace", default=None)

_LOGGER_NAME = "knowledge_assistant"


def get_logger(name: str) -> logging.Logger:
    """Every module logs through a child of one root logger, so handlers attach once."""
    return logging.getLogger(f"{_LOGGER_NAME}.{name}")


def log_event(logger: logging.Logger, event: str, **fields) -> None:
    """Emit a structured event.

    `event` is a dotted, greppable name - "citations.stripped", "guardrail.rejected" - not a
    sentence. Sentences cannot be counted; "how often does the model invent a citation" is a
    question about a hundred requests, and prose cannot answer it.

    Values in **fields must be counts, verdicts, identifiers, or shapes. Never content.
    """
    logger.info(event, extra={"fields": fields})


class TraceHandler(logging.Handler):
    """Appends every record to the current turn's trace, if there is one."""

    def emit(self, record: logging.LogRecord) -> None:
        trace = _current_trace.get()

        if trace is None:
            return

        trace.append({
            "event": record.getMessage(),
            "level": record.levelname,
            "logger": record.name.removeprefix(f"{_LOGGER_NAME}."),
            "fields": getattr(record, "fields", {}),
            "at": record.created,
        })


class _FieldFormatter(logging.Formatter):
    """Renders structured fields as key=value so the file stays greppable."""

    def format(self, record: logging.LogRecord) -> str:
        base = super().format(record)
        fields = getattr(record, "fields", {})

        if not fields:
            return base

        rendered = " ".join(f"{key}={value!r}" for key, value in fields.items())
        return f"{base}  {rendered}"


def configure_logging() -> None:
    """Attach handlers once per process.

    IDEMPOTENT ON PURPOSE. Streamlit re-executes the whole script on every interaction, so a
    naive setup would attach a second file handler, then a third - duplicated lines and leaked
    file descriptors, growing for the life of the session. The `if logger.handlers` guard is
    load-bearing, not defensive habit.
    """
    logger = logging.getLogger(_LOGGER_NAME)

    if logger.handlers:
        return

    logger.setLevel(LOG_LEVEL)

    # Do not also bubble up to the root logger - Streamlit configures that, and we would get
    # every line twice.
    logger.propagate = False

    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)

    # RETENTION BY ROTATION, NOT BY DELETION.
    #
    # The policy is "keep a week". The naive implementation - scan the file daily and remove
    # lines older than 7 days - means rewriting the whole file every day: O(file size), and not
    # atomic, so a crash mid-rewrite loses the log you were preserving.
    #
    # Rotation makes the unit of retention a FILE. Renaming is atomic and dropping the oldest
    # file is free, regardless of how large it grew. Same reason Kafka expires whole segments
    # rather than compacting records out of them.
    #
    # The rollover check runs on WRITE, not on a timer - nothing is scheduled and nothing runs
    # while the app is idle. Consequence: if the app is not opened for three weeks, nothing
    # rotates in the meantime. Retention is "7 rotations", which for an app that runs when you
    # run it is roughly seven days of USE, not seven calendar days.
    file_handler = TimedRotatingFileHandler(
        LOG_FILE,
        when="midnight",
        backupCount=LOG_RETENTION_DAYS,
        encoding="utf-8",
    )
    file_handler.setFormatter(
        _FieldFormatter("%(asctime)s %(levelname)-5s %(name)s %(message)s")
    )

    logger.addHandler(file_handler)
    logger.addHandler(TraceHandler())


def start_turn() -> tuple[list, object]:
    """Begin collecting events for one turn.

    Returns the (empty) trace list and the token that ends it. The list is handed straight to
    StreamedAnswer, and it is MUTABLE on purpose: the deferred summarization runs after the
    response object already exists, so its events have to be able to land in a list somebody is
    already holding. A snapshot taken when the response was built would silently drop every
    summary event - including "summary.rejected", one of the six blind spots.

    Same lesson as PR-12's sidebar: anything captured before the state changed is stale.
    """
    trace: list = []
    token = _current_trace.set(trace)
    return trace, token


def end_turn(token) -> None:
    """Restore the previous trace context. Always paired with start_turn()."""
    _current_trace.reset(token)


class stage:
    """Times a pipeline stage and logs its duration on exit.

    A context manager rather than a decorator because the interesting stages are regions inside
    functions - "retrieval", "generation" - not whole functions.
    """

    def __init__(self, logger: logging.Logger, name: str, **fields):
        self._logger = logger
        self._name = name
        self._fields = fields

    def __enter__(self):
        self._started = time.perf_counter()
        return self

    def __exit__(self, exc_type, exc, tb):
        elapsed_ms = round((time.perf_counter() - self._started) * 1000)

        # Log the failure too. A stage that raised is the single most useful line in the file,
        # and it is exactly the one a naive implementation loses by only logging on success.
        log_event(
            self._logger,
            f"{self._name}.failed" if exc_type else f"{self._name}.done",
            ms=elapsed_ms,
            **self._fields,
            **({"error": exc_type.__name__} if exc_type else {}),
        )

        return False
