# Helios Ingest API — Developer Guide (v3.2)

**Status:** General Availability
**Last reviewed:** 2026-01-14
**Owner:** Platform API team (`platform-api@helios.example.com`)
**On-call rotation:** `helios-ingest`

The Helios Ingest API accepts event batches from customer applications and writes them
to the Helios event lake. This guide covers authentication, limits, error handling,
pagination, and webhooks. It does not cover the Query API, which is documented
separately in the Helios Query Reference.

---

## 1. Base URL and versioning

All requests go to:

```
https://api.helios.example.com/v3
```

The version lives in the path, never in a header. Version `v2` reached end of life and
is scheduled for sunset on **2026-03-31**; after that date `v2` requests return HTTP 410
with the error code `version_retired`. There is no automatic redirect from `v2` to `v3`
because the batch envelope changed shape between the two versions.

Breaking changes are only ever introduced behind a new major version. Additive changes —
new optional fields, new enum members, new error codes — may ship into an existing
version without notice, so clients must ignore unknown JSON fields rather than reject
them.

---

## 2. Authentication

Every request carries an API key in the `X-Helios-Key` header. Keys are environment
scoped by prefix:

- `hlk_live_...` — production keys, write to the real event lake, billed.
- `hlk_test_...` — sandbox keys, write to a throwaway namespace purged nightly at 03:00 UTC.

```bash
curl -X POST https://api.helios.example.com/v3/events \
  -H "X-Helios-Key: hlk_live_9f2c41ab7d" \
  -H "Content-Type: application/json" \
  -d '{"events":[{"type":"order.created","payload":{"id":"A-1099"}}]}'
```

A key that is missing, malformed, or revoked returns HTTP 401 with error code
`invalid_key`. A key that is valid but lacks the `events:write` scope returns HTTP 403
with `insufficient_scope`. Those two are deliberately different: 401 means "we do not
know who you are", 403 means "we know exactly who you are and the answer is still no".

Keys never expire on a timer. They are revoked explicitly from the Helios console, and
revocation takes effect within 60 seconds across all regions.

---

## 3. Rate limits

The Ingest API allows **240 requests per minute per API key**, with a burst allowance of
**40 requests**. The limiter is a token bucket refilling at 4 tokens per second, so a
client that has been idle can spend its burst immediately and then settles into the
steady rate.

Limits are enforced per key, not per account. Splitting traffic across two keys doubles
the effective ceiling, which is the supported way to scale a noisy batch job away from
your interactive traffic.

When the bucket empties, the API returns HTTP 429 with a `Retry-After` header in whole
seconds. Clients must honour `Retry-After` rather than retrying immediately, and should
apply exponential backoff with jitter on top of it. Three consecutive 429 responses from
the same key within 60 seconds also emit a `rate_limit.sustained` webhook so operators
notice throttling without reading logs.

Every response — successful or not — carries the current limiter state:

| Header | Meaning |
| --- | --- |
| `Helios-RateLimit-Limit` | Requests permitted in the current window (240) |
| `Helios-RateLimit-Remaining` | Requests left in the current window |
| `Helios-RateLimit-Reset` | Unix timestamp when the window refills |

---

## 4. Payload limits

A single request body may not exceed **5 MiB** after decompression, and a single batch
may not contain more than **500 events**. Exceeding either returns HTTP 413 with error
code `payload_too_large`; the API does not partially accept an oversized batch, because a
half-written batch is far harder for a client to reason about than a clean rejection.

Individual event payloads are capped at 256 KiB. Requests may be gzip-compressed by
sending `Content-Encoding: gzip`, and compressed bodies are measured against the 5 MiB
limit *after* decompression to prevent zip-bomb style abuse.

---

## 5. Idempotency

Any mutating request may carry a `Helios-Idempotency-Key` header containing a
client-generated UUID. Helios stores the outcome of that request for **24 hours** and
replays the stored response verbatim for any repeat of the same key, including the
original status code.

This is the intended way to make retries safe. A client that times out waiting for a
response cannot tell whether the batch was written; retrying with the same idempotency
key resolves that ambiguity without risking duplicate events.

If the same idempotency key arrives with a *different* request body, Helios returns HTTP
409 with error code `idempotency_conflict` rather than guessing which body was meant.

---

## 6. Error codes

| HTTP | Code | Retryable | Meaning |
| --- | --- | --- | --- |
| 400 | `malformed_json` | No | Body is not valid JSON |
| 400 | `schema_violation` | No | A required field is missing or mistyped |
| 401 | `invalid_key` | No | Key missing, malformed, or revoked |
| 403 | `insufficient_scope` | No | Key lacks `events:write` |
| 409 | `idempotency_conflict` | No | Key reused with a different body |
| 413 | `payload_too_large` | No | Over 5 MiB or over 500 events |
| 429 | `rate_limited` | Yes | Token bucket empty; honour `Retry-After` |
| 503 | `region_draining` | Yes | Region is failing over; retry after backoff |
| 504 | `upstream_timeout` | Yes | Write path exceeded the 30-second budget |

Only the codes marked retryable should ever be retried automatically. Retrying a
`schema_violation` produces the same failure forever while consuming rate limit budget
that the client's healthy traffic needs.

---

## 7. Pagination

List endpoints use opaque cursors, never numeric offsets. A response containing more
results includes a `next_cursor` string; pass it back as the `cursor` query parameter to
fetch the following page. The default page size is **50** and the maximum is **200**.

Cursors are valid for 15 minutes. An expired cursor returns HTTP 400 with
`cursor_expired`, and the correct recovery is to restart the listing from the beginning
rather than to guess an offset. Offsets were removed in v3 precisely because pages
shifted underneath clients whenever new events landed mid-iteration.

---

## 8. Webhooks

Helios signs every webhook delivery with HMAC-SHA256 over the raw request body, using
the endpoint's signing secret. The signature arrives in the `Helios-Signature` header
alongside a Unix timestamp:

```
Helios-Signature: t=1768392000,v1=8a1f...c904
```

Receivers must reject any delivery whose timestamp is more than **300 seconds** away from
their own clock, which is what stops a captured payload from being replayed later.
Compare signatures with a constant-time function; a naive string equality check leaks
timing information about the expected value.

Deliveries are retried on any non-2xx response for up to **24 hours** with exponential
backoff, and an endpoint returning non-2xx for 24 consecutive hours is automatically
disabled and its owner emailed.

---

## 9. Data retention

Ingested events are retained for **90 days** on the Standard plan and **400 days** on the
Enterprise plan. Retention is measured from event ingestion time, not from event
timestamp, so backfilled historical data still gets a full window.

Deletion requests submitted through the console are honoured within 30 days across
primary storage, replicas, and backups.

---

## 10. Support

Route production incidents to the `helios-ingest` on-call rotation. Non-urgent questions
go to `platform-api@helios.example.com` with a response target of one business day.
Include the `Helios-Request-Id` response header in every report — it is the only value
that lets support locate a single request in the write path logs.
