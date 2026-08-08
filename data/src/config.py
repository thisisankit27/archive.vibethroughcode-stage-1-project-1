"""Application configuration.

Every value here was a hardcoded literal somewhere in the codebase, and every one of them
is something a person might need to change WITHOUT a code change: swapping a model, moving
storage onto a mounted volume, tuning retrieval, pointing at a remote Ollama.

    OLLAMA_BASE_URL         http://localhost:11434 by default
    GENERATION_MODEL        llama3.2:latest
    SUMMARIZATION_MODEL     llama3.2:latest
    EMBEDDING_MODEL         embeddinggemma:latest
    EMBEDDING_BATCH_SIZE    100
    TOP_K                   3
    RRF_K                   60
    CHUNK_SIZE              600
    CHUNK_OVERLAP           300
    STORAGE_DIR             ./storage
    FLUSH_FLOOR             20

WHY ENVIRONMENT VARIABLES AND NOT A FILE

A config file needs a loader, a location, a format, and a decision about what happens when
it is missing or malformed - four new failure modes to buy an ergonomic win this project
does not need yet. Environment variables are already how a container, a systemd unit, and
Streamlit Cloud all expect to be configured, so this is the format PR-16 will need anyway.

Deliberately NOT using python-dotenv: this project's virtualenv is a DIRECTORY named
`.env`, so a loader looking for a `.env` FILE would collide with it. Export the variables,
or set them in whatever runs the app.

WHY IT FAILS AT IMPORT

_env_int raises on garbage rather than falling back to the default. TOP_K="abc" should stop
the application at startup with a readable message, not surface as a TypeError deep inside
FAISS on the first question anyone asks.

  Fail at startup where the operator is watching, not at request time where a user is.
"""

import os
from pathlib import Path


def _env_str(name: str, default: str) -> str:
    return os.getenv(name, default)


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)

    if raw is None:
        return default

    try:
        return int(raw)
    except ValueError:
        raise ValueError(
            f"Configuration error: {name}={raw!r} is not an integer."
        ) from None


# --------------------------------------------------
# Models
# --------------------------------------------------
# base_url is None by default so langchain applies its own localhost default. It exists
# because "runs against a local Ollama" is the assumption most likely to break the moment
# this is deployed anywhere (PR-16).
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL")

# Two separate keys, even though they hold the same value today. They change for different
# reasons: answering may want a larger model while summarizing stays cheap. One shared key
# would silently couple those decisions together.
GENERATION_MODEL = _env_str("GENERATION_MODEL", "llama3.2:latest")
SUMMARIZATION_MODEL = _env_str("SUMMARIZATION_MODEL", "llama3.2:latest")

EMBEDDING_MODEL = _env_str("EMBEDDING_MODEL", "embeddinggemma:latest")
EMBEDDING_BATCH_SIZE = _env_int("EMBEDDING_BATCH_SIZE", 100)


# --------------------------------------------------
# Retrieval
# --------------------------------------------------
TOP_K = _env_int("TOP_K", 3)

# The RRF damping constant. 60 is the value from the original paper and is rarely tuned,
# but it is exactly the kind of number someone eventually wants to experiment with.
RRF_K = _env_int("RRF_K", 60)


# --------------------------------------------------
# Chunking
# --------------------------------------------------
# Changing either of these invalidates the existing index - the stored vectors were built
# from differently-shaped chunks. Configurable, but not a knob to turn casually.
CHUNK_SIZE = _env_int("CHUNK_SIZE", 600)
CHUNK_OVERLAP = _env_int("CHUNK_OVERLAP", 300)


# --------------------------------------------------
# Storage
# --------------------------------------------------
# ONE directory, four paths derived from it.
#
# Before this, the same paths were written out in three modules - and one of the three was
# both unused and wrong, pointing at a sparse index filename that has never existed. That
# is what duplicated configuration decays into: copies that drift, with nothing to notice.
#
# Deriving all four from one root also makes the deployment question a single answer:
# "where does state live" is one variable, not four.
STORAGE_DIR = Path(_env_str("STORAGE_DIR", "./storage"))

DENSE_INDEX_PATH = STORAGE_DIR / "my_index.index"
SPARSE_INDEX_PATH = STORAGE_DIR / "bm25.index"
DOCUMENTS_PATH = STORAGE_DIR / "documents.pkl"
CATALOG_PATH = STORAGE_DIR / "metadata_catalog.json"


# --------------------------------------------------
# Streaming
# --------------------------------------------------
# How many chunks accumulate before a flush is considered. A UX judgment, tuned by feel.
FLUSH_FLOOR = _env_int("FLUSH_FLOOR", 20)

# DERIVED, NOT CONFIGURED - and refusing to make this a setting is the point.
#
# MARKER_MAX is how long an unmatched "[" may be held before it is ruled out as a citation.
# Its correct value is not a preference: the longest valid marker is "[" + str(TOP_K) + "]",
# so the bound follows arithmetically from TOP_K.
#
# Exposing it as its own variable would let someone set TOP_K=12 and leave MARKER_MAX at 3,
# which silently truncates every two-digit citation - a settings-page bug with no error
# message. Deriving it makes that combination impossible to express.
#
#   If a value can be computed from another value, it is not configuration.
#   It is a bug waiting for someone to disagree with itself.
MARKER_MAX = len(str(TOP_K)) + 2


# --------------------------------------------------
# Deliberately NOT configured here
# --------------------------------------------------
# The summary's 3-sentence cap. It is a number embedded in an English sentence inside
# SUMMARY_SYSTEM_PROMPT, and PR-11a already decided prompt wording is owned by prompts.py.
# Lifting the digit out would either template prose for no real gain, or - worse - create a
# second place the limit is stated, free to disagree with the sentence the model reads.
#
# The typewriter timings in app.py, for the same reason in a different direction: they are
# presentation, tuned by eye against a running page, not operational settings anyone would
# set in an environment.
