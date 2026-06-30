# Artha Transaction Processing Pipeline

An async, AI-powered backend for ingesting dirty CSV transaction exports, cleaning them,
detecting anomalies, classifying spend with an LLM, and surfacing a structured summary
through a polling API.

Built for the Backend + DevOps internship assignment.

## Quickstart

```bash
git clone <this-repo-url>
cd artha-txn-pipeline
cp .env.example .env
docker compose up --build
```

That's it — no manual migration step, no manual Redis/Postgres setup. The API container
runs `Base.metadata.create_all()` on startup. API is live at `http://localhost:8000`,
interactive docs at `http://localhost:8000/docs`.

By default `.env` ships with `LLM_PROVIDER=mock`, so the whole pipeline — classification
*and* narrative generation — runs fully offline with a deterministic keyword classifier.
This means the grader can `docker compose up` and hit every endpoint with **zero API key
and zero spend**, while the code path is identical to the real LLM path. To use a real
model, set `LLM_PROVIDER=gemini` and `GEMINI_API_KEY=<your free-tier key>` in `.env`.

## Example requests

```bash
# Upload
curl -X POST http://localhost:8000/jobs/upload \
  -F "file=@transactions.csv"
# -> {"id": "abc-123", "status": "pending", ...}

# Poll status
curl http://localhost:8000/jobs/abc-123/status

# Fetch full results once completed
curl http://localhost:8000/jobs/abc-123/results

# List jobs, optionally filtered
curl "http://localhost:8000/jobs?status=completed"
```

## The one design decision worth highlighting: a persistent merchant→category cache

The brief asks to "batch your LLM calls, not one call per row" — that handles the
*within-job* cost problem. But at any real scale, the actual bottleneck isn't rows within
one upload, it's that the same ~30 merchants (Swiggy, Amazon, IRCTC, Ola...) appear in
*every single user's* CSV, every month. A naive batched-per-job implementation still
re-asks the LLM "what category is Swiggy?" on every upload, forever.

`MerchantCategoryCache` is a small Postgres table (`merchant_normalized -> category,
confidence, hit_count`) that persists **across jobs, across users**. Before a batch is
sent to the LLM, every merchant needing classification is checked against this table
first; only genuinely unseen merchants go into the LLM batch. The job summary reports
`llm_calls_made` vs `llm_calls_saved_by_cache` so the effect is directly observable per
run. After the first few real-world uploads, the cache hit rate for a consumer fintech
app like this would realistically converge above 90%, since merchant vocabulary is a long
tail with a short, repeating head.

This is a genuine architectural choice with a trade-off, not just a nice-to-have: it
trades a small amount of staleness (a merchant's category won't auto-update if the LLM
would classify it differently next month) for a large, permanent reduction in LLM cost
and latency. See "Bottlenecks & Scale" below for how this evolves at 100x traffic.

## Architecture

* **Architecture Diagram (PNG)**: [View on Google Drive](https://drive.google.com/file/d/1rLvq-jEkvLnd0F_5IEMLN-Rhn2B1OkRI/view?usp=sharing)
* **Draw.io Source Diagram (.drawio)**: [View on Google Drive](https://drive.google.com/file/d/1dV-NBipXqWkxxd7tbpF_5SCe3MxWW9Dk/view?usp=drive_link)

```
                         ┌────────────┐
        POST /jobs/upload│            │  1. validate CSV, save to disk
   ───────────────────▶  │  FastAPI   │  2. create Job row (status=pending)
                         │   (API)    │  3. enqueue Celery task
                         └─────┬──────┘  4. return job_id immediately
                               │
                               ▼
                         ┌────────────┐
                         │   Redis    │  broker (queue) + result backend
                         └─────┬──────┘
                               ▼
                         ┌────────────┐
                         │   Celery   │  a) clean (dates/amounts/dupes)
                         │   Worker   │  b) detect anomalies (stat + rule)
                         └─────┬──────┘  c) classify via merchant cache + LLM batch
                               │         d) LLM narrative summary (JSON)
                               ▼         e) retry w/ exponential backoff, llm_failed flag
                         ┌────────────┐
                         │ PostgreSQL │  Job, Transaction, JobSummary,
                         │            │  MerchantCategoryCache (cross-job)
                         └────────────┘
                               ▲
                               │  GET /jobs/{id}/status
   ◀───────────────────────────  GET /jobs/{id}/results  (polled by client)
```

**Request lifecycle for a single upload:** client posts the file to `/jobs/upload` ->
FastAPI streams it to disk, computes a SHA-256 checksum, writes a `Job` row with
`status=pending`, and calls `process_job.delay(job_id, file_path)`, returning the
`job_id` synchronously. Celery (via Redis) picks up the task on a worker process. The
worker loads the CSV with pandas, runs cleaning -> anomaly detection -> classification ->
narrative generation in sequence, updating `Job.progress_pct` and writing `Transaction`
rows as it goes, then writes one `JobSummary` row and flips `Job.status=completed`. The
client polls `/jobs/{id}/status` (cheap, no joins) until `completed`, then calls
`/jobs/{id}/results` for the full joined payload.

### Why this folder structure / schema
- `app/services/` holds pure functions (cleaning, anomaly, llm) with no DB or Celery
  dependency, so they're independently unit-testable (see the inline smoke tests used
  during development) — `app/workers/tasks.py` is the only place that wires them to
  persistence.
- `row_hash` for dedup is computed on normalized *business fields* (date, merchant,
  amount, currency, account), not `txn_id` — several real rows in the sample CSV have a
  blank `txn_id` but are still exact duplicates by content.
- `MerchantCategoryCache` is a separate table, not a column on `Transaction`, because its
  lifecycle is cross-job and append-only, unlike everything else which is job-scoped.

## Bottlenecks & Scale (100x traffic)

**Where it breaks first:**
1. **Single worker queue, no priority/isolation.** All jobs share one Celery queue —
   a 50MB CSV from one user blocks faster jobs behind it. At 100x, p95 latency for small
   uploads would spike badly.
2. **Synchronous LLM calls inside the task, one task = one DB session held open.**
   `process_job` holds a single SQLAlchemy session for the full pipeline duration,
   including LLM network round-trips. At 100x concurrency this exhausts the Postgres
   connection pool (`pool_size=10` here) fast — that's the actual breaking point, not CPU.
3. **`Base.metadata.create_all()` and CSV-to-pandas in memory.** Fine for ~100-row demo
   files; a genuinely large CSV read fully into a pandas DataFrame in worker memory
   doesn't scale, and `create_all` isn't safe for concurrent schema evolution anyway.

**Next iteration for production scale:**
- Split the pipeline into discrete Celery tasks chained with `chain()`/`chord()` (clean ->
  anomaly -> classify -> narrate) so each step can be retried, scaled, and observed
  independently, and so a DB session is only held for the duration of its own step, not
  the whole job. Trade-off: more inter-task state needs to round-trip through Postgres or
  Redis instead of living in one Python scope, adding serialization overhead.
- Move the merchant cache from Postgres to Redis (or a dedicated lookup service) as a true
  read-through cache in front of the LLM, with Postgres as the system-of-record synced
  asynchronously. Trade-off: eventual consistency between the fast cache and the durable
  table.
- Stream large CSVs in chunks (`pd.read_csv(..., chunksize=...)`) instead of loading the
  whole file, and move file storage from local disk to S3-compatible object storage so API
  and worker containers can scale horizontally without a shared volume.
- Switch Alembic migrations into the deploy pipeline instead of `create_all()`, and add a
  dedicated `priority` queue (Celery supports multiple queues/routes) so small jobs aren't
  blocked behind large ones.
- Add per-tenant rate limiting on `/jobs/upload` and a circuit breaker around the LLM
  provider so a degraded LLM API doesn't back up the whole queue — fall back to
  rule-based categorization for the duration of the outage.

## Tech stack
FastAPI, PostgreSQL, Celery + Redis, pandas, Gemini 1.5 Flash (free tier) with a
deterministic offline mock fallback, Docker Compose.

## Project layout
```
app/
  api/        # FastAPI routes + pydantic schemas
  core/       # config, db session
  models/     # SQLAlchemy models (Job, Transaction, JobSummary, MerchantCategoryCache)
  services/   # pure logic: cleaning, anomaly detection, LLM calls
  workers/    # Celery app + the orchestrating task
docker/Dockerfile
docker-compose.yml
transactions.csv   # sample input for quick testing
```
