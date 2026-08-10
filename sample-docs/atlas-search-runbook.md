# Atlas Search Cluster — On-Call Runbook

**Cluster:** `atlas-prod-eu1`
**Status:** Authoritative — this runbook wins over tribal knowledge
**Last reviewed:** 2026-02-02
**Owner:** Search Infrastructure team (`search-infra@helios.example.com`)
**Escalation rotation:** `atlas-oncall`

This runbook covers the production Atlas search cluster that serves the customer-facing
search box and the internal analytics console. It assumes you already hold cluster
credentials and can reach the bastion. If you cannot, stop and page the secondary rather
than spending the incident fixing your own access.

---

## 1. Cluster topology

`atlas-prod-eu1` runs **9 nodes**: 3 dedicated master nodes and 6 data nodes, spread
across three availability zones. Masters hold no shard data. Every index is configured
with one primary and one replica, so the cluster survives the loss of any single zone
without data loss.

The ingest pipeline reads from the Helios event lake and writes into Atlas. It is a
downstream consumer of the Helios Ingest API, which means an upstream Helios incident
surfaces here first as indexer lag, not as query errors.

| Role | Count | Instance | Notes |
| --- | --- | --- | --- |
| Master | 3 | `m6i.large` | Quorum is 2; never run with fewer than 3 |
| Data | 6 | `r6i.2xlarge` | 2 TB gp3 volume each |
| Coordinator | 2 | `c6i.xlarge` | Stateless, behind the load balancer |

---

## 2. Service level objectives

- **p99 query latency** stays under **350 ms**, measured at the coordinator nodes.
- **Availability** is **99.95%** per calendar month, which allows **21.6 minutes** of
  error budget in a 30-day month.
- **Indexing freshness**: a document written to the event lake is searchable within
  **5 minutes** at p95.

Burning more than half the monthly error budget in a single week triggers a mandatory
reliability review and freezes non-critical deploys to the cluster until the review
closes.

---

## 3. Alerts

### AtlasQueryLatencyHigh (warning)

Fires when p99 query latency exceeds 350 ms for 10 minutes. Usual causes, in the order
they actually happen:

1. A single expensive query pattern — check the slow query log first.
2. Segment merge pressure after a large bulk index.
3. A hot shard, where one shard receives disproportionate traffic.

Mitigation is to identify and block the offending query pattern at the coordinator, then
address the underlying shard imbalance during business hours. Do not restart nodes to
clear latency; a restart triggers shard relocation and makes the symptom worse for
20–40 minutes.

### AtlasIndexerLagCritical (page)

Indexer lag is the age of the oldest unindexed document. Warning fires at **5 minutes**,
critical pages at **15 minutes**.

The ingest pipeline throttles itself at **12,000 documents per second** to protect the
data nodes. When the upstream backlog exceeds that rate the lag grows linearly and will
not recover on its own — this is the alert most often mistaken for a transient blip.
Check whether the throttle is the binding constraint before scaling anything:

```bash
atlasctl indexer status --cluster atlas-prod-eu1
atlasctl indexer lag --cluster atlas-prod-eu1 --window 30m
```

If the throttle is saturated and the backlog is still growing, raise the throttle in
increments of 2,000 documents per second, waiting 5 minutes between steps and watching
p99 latency. Stop raising it the moment query latency degrades — search availability
outranks indexing freshness in every case.

### AtlasDiskPressure (page)

Atlas applies a **high watermark at 85%** disk usage, at which point it stops allocating
new shards to the affected node. At the **flood stage of 95%** it puts every index with a
shard on that node into read-only mode, which halts indexing cluster-wide and is a
customer-visible outage.

Recovery from flood stage is not automatic. After freeing space you must explicitly clear
the read-only block:

```bash
atlasctl index unblock --cluster atlas-prod-eu1 --all
```

---

## 4. Escalation path

| Time from page | Action |
| --- | --- |
| 0 min | L1 on-call acknowledges |
| 20 min | Escalate to L2 (Search Infrastructure) if not mitigated |
| 45 min | Escalate to L3 and open a vendor support ticket at Severity 1 |
| 60 min | Incident commander declares a customer-facing incident |

Escalating early is never criticised in review. The 20-minute mark is a ceiling, not a
target — if you know at minute 3 that you are out of depth, escalate at minute 3.

---

## 5. Common procedures

### Rolling restart

```bash
atlasctl rollout restart --cluster atlas-prod-eu1 --max-unavailable 1
```

Disable shard allocation before starting and re-enable it afterwards, otherwise the
cluster relocates shards around every node as it cycles and the restart takes hours
instead of minutes.

### Rolling back a bad deploy

```bash
atlasctl rollout undo --cluster atlas-prod-eu1
```

Rollback is the first response to any regression that appeared within 30 minutes of a
deploy. Diagnose afterwards, from the rolled-back state — a running system with a known
good version buys you the time to investigate properly.

### Snapshots and restore

Snapshots run **every 6 hours** to `s3://atlas-backups-eu1` and are retained for
**30 days**. The measured restore time for a full cluster is **90 minutes** (RTO), and
worst-case data loss is one snapshot interval, **6 hours** (RPO).

Restore drills run quarterly against a scratch cluster. A snapshot that has never been
restored is a hypothesis, not a backup.

---

## 6. Client-side expectations

Search clients must treat HTTP 429 and 503 from the coordinator as retryable, honour the
`Retry-After` header, and apply exponential backoff with jitter. Clients that retry
immediately turn a recoverable degradation into a stampede — during the 2025-11-08
incident, aggressive client retries tripled load on an already-saturated cluster and
extended the outage by roughly 25 minutes.

The coordinator enforces a **10-second query timeout**. A query exceeding it is cancelled
and returns HTTP 504; retrying an identical expensive query is pointless and costs the
cluster the same work twice.

---

## 7. After the incident

Any page that consumes more than 10 minutes of error budget requires a written
postmortem within **5 business days**. Postmortems are blameless and must state what was
known at each decision point rather than what was knowable in hindsight.

Every postmortem action item gets an owner and a due date, or it is not an action item.
If this runbook was wrong or missing a step during the incident, updating it *is* the
first action item.
