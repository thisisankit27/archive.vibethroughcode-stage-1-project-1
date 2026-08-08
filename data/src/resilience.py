"""Retry policy and failure classification for external calls.

Every call to Ollama can fail, and "wrap it in try/except and retry three times" is the wrong
answer to all of them. A failure has to pass TWO independent tests before it may be retried.

TEST 1 - IS IT TRANSIENT?

    httpx.ConnectError        Ollama is not running          -> retry, it may come back
    httpx.ReadTimeout         model loading, slow generation -> retry
    ResponseError 5xx         server-side fault              -> retry
    ResponseError 404         llama3.2:latest was never pulled -> NEVER
    KeyError in a template    a code bug                     -> NEVER

    Retrying a DETERMINISTIC failure buys the same error, N times slower. A 404 for an
    unpulled model retried three times with backoff is seven seconds of waiting to print
    the message you already had on attempt one.

TEST 2 - IS IT IDEMPOTENT?

    Generation has no side effects, so a retry is free.

    VectorStore.store() is NOT idempotent - it does index.add() then documents.extend() then
    save(). Retry it after a failed save and every chunk is in the index twice. Nothing in
    this module is applied to indexing, and that is deliberate rather than an oversight.

WHY THE DOMAIN NEVER SEES httpx

Callers catch DependencyError, not httpx.ConnectError. rag.py has no business importing an
HTTP library to decide what to tell a user - the same instinct as PR-10's INVARIANT #2:
translate infrastructure types into domain types at the boundary you own.

NOT BUILT: a circuit breaker. If Ollama is overloaded and every client retries three times,
retries triple the load on a dying service - so beyond some budget you must stop trying
entirely. With one local user and one local Ollama there is no herd to protect against. Noted
because "I know why a breaker exists and why I did not need one" is the honest position.
"""

import random
import time
from typing import Callable, Iterator, TypeVar

import httpx

from data.src.config import LLM_BACKOFF_BASE_SECONDS, LLM_MAX_ATTEMPTS
from data.src.observability import get_logger, log_event

_logger = get_logger("resilience")

T = TypeVar("T")

# Network-level faults. Every one of these means "the request did not get a considered answer",
# which is precisely the case where trying again can change the outcome.
_TRANSIENT_NETWORK_ERRORS = (
    httpx.ConnectError,
    httpx.ConnectTimeout,
    httpx.ReadTimeout,
    httpx.WriteTimeout,
    httpx.PoolTimeout,
    httpx.RemoteProtocolError,
)


class DependencyError(Exception):
    """An external dependency could not serve this request.

    Carries a domain `reason` rather than the underlying exception type, so callers branch on
    a stable code instead of on whichever HTTP library happens to be underneath.
    """

    def __init__(self, dependency: str, reason: str, message: str, attempts: int = 1):
        super().__init__(message)
        self.dependency = dependency
        self.reason = reason
        self.message = message
        self.attempts = attempts


def _status_code(error: Exception) -> int | None:
    """Ollama's ResponseError carries a status code; httpx status errors carry a response."""
    code = getattr(error, "status_code", None)
    if isinstance(code, int):
        return code

    response = getattr(error, "response", None)
    return getattr(response, "status_code", None)


def is_transient(error: Exception) -> bool:
    """Whether trying the same call again could plausibly produce a different result."""

    if isinstance(error, _TRANSIENT_NETWORK_ERRORS):
        return True

    code = _status_code(error)

    if code is None:
        # An unrecognised exception is treated as PERMANENT. That is the safe default: a
        # wrongly-retried bug costs latency on every request, while a wrongly-not-retried
        # blip costs one failed request that the user can repeat themselves.
        return False

    # 5xx is the server failing at something it agreed to do - worth another attempt.
    # 4xx is the server telling you the request itself is wrong. Repeating it verbatim
    # cannot help, and 404 here means the model was never pulled.
    return code >= 500


def _classify(dependency: str, error: Exception, attempts: int) -> DependencyError:
    code = _status_code(error)

    if code == 404:
        return DependencyError(
            dependency,
            "LLM_MISCONFIGURED",
            "The configured model is not available on the Ollama server. "
            "Check GENERATION_MODEL / EMBEDDING_MODEL, or pull the model.",
            attempts,
        )

    if isinstance(error, _TRANSIENT_NETWORK_ERRORS):
        return DependencyError(
            dependency,
            "LLM_UNAVAILABLE",
            "Could not reach the language model. It may be starting up, or not running.",
            attempts,
        )

    return DependencyError(
        dependency,
        "LLM_ERROR",
        "The language model returned an error.",
        attempts,
    )


def _sleep_before_retry(attempt: int) -> None:
    """Exponential backoff with full jitter.

    BACKOFF: retrying instantly just hits the same dead socket. The growing delay is what
    gives the dependency room to recover.

    JITTER: without it, every client that failed at the same instant waits the SAME interval
    and retries at the same millisecond - a synchronized wave that re-kills a service just as
    it comes back up. Randomising spreads them.

    With one local user there is no herd, so this is insurance rather than a fix. It is one
    line, which is cheaper than explaining its absence later.
    """
    ceiling = LLM_BACKOFF_BASE_SECONDS * (2 ** attempt)
    time.sleep(random.uniform(0, ceiling))


def call_with_retry(operation: str, dependency: str, call: Callable[[], T]) -> T:
    """Run `call`, retrying only transient failures. Raises DependencyError on give-up.

    Only ever wrap calls with NO SIDE EFFECTS. See the module docstring on VectorStore.store.
    """
    last_error: Exception | None = None

    for attempt in range(LLM_MAX_ATTEMPTS):
        try:
            return call()
        except Exception as error:  # noqa: BLE001 - classified immediately below
            last_error = error

            if not is_transient(error):
                # Permanent. Stop now - further attempts produce the identical failure and
                # only add latency before the user sees the message.
                log_event(
                    _logger,
                    "dependency.failed",
                    dependency=dependency,
                    operation=operation,
                    error=type(error).__name__,
                    transient=False,
                    attempts=attempt + 1,
                )
                raise _classify(dependency, error, attempt + 1) from error

            if attempt + 1 < LLM_MAX_ATTEMPTS:
                log_event(
                    _logger,
                    "dependency.retrying",
                    dependency=dependency,
                    operation=operation,
                    error=type(error).__name__,
                    attempt=attempt + 1,
                    of=LLM_MAX_ATTEMPTS,
                )
                _sleep_before_retry(attempt)

    log_event(
        _logger,
        "dependency.failed",
        dependency=dependency,
        operation=operation,
        error=type(last_error).__name__,
        transient=True,
        attempts=LLM_MAX_ATTEMPTS,
    )
    raise _classify(dependency, last_error, LLM_MAX_ATTEMPTS) from last_error


def retryable_stream(
    operation: str,
    dependency: str,
    open_stream: Callable[[], Iterator[T]],
) -> Iterator[T]:
    """Retry only until the FIRST item arrives; never after output has been emitted.

    This is the rule that makes streaming different. Once a token has been handed to the
    caller - and, one layer up, painted on the user's screen - restarting the stream would
    replay it. The user would watch the answer begin twice.

    So the retry window is exactly the connection phase. Conveniently that is also where the
    common failure lives: Ollama being down fails on the first chunk, which is precisely when
    retrying is both safe and useful.

    Errors after the first item propagate as a DependencyError with attempts=1 - honest, since
    no retry was attempted.
    """
    stream = call_with_retry(operation, dependency, open_stream)
    iterator = iter(stream)

    try:
        first = next(iterator)
    except StopIteration:
        return
    except Exception as error:  # noqa: BLE001
        # The generator was lazy, so the connection actually happened here rather than inside
        # call_with_retry. Retry the whole open-and-first-pull as one unit.
        def _reopen():
            reopened = iter(open_stream())
            return next(reopened), reopened

        if not is_transient(error):
            raise _classify(dependency, error, 1) from error

        log_event(
            _logger,
            "dependency.retrying",
            dependency=dependency,
            operation=f"{operation}.first_chunk",
            error=type(error).__name__,
        )
        first, iterator = call_with_retry(f"{operation}.reopen", dependency, _reopen)

    yield first

    # From here on there is no safety net. Output has left the building.
    try:
        yield from iterator
    except Exception as error:  # noqa: BLE001
        log_event(
            _logger,
            "dependency.failed",
            dependency=dependency,
            operation=f"{operation}.mid_stream",
            error=type(error).__name__,
            transient=is_transient(error),
            attempts=1,
            partial_output=True,
        )
        raise _classify(dependency, error, 1) from error
