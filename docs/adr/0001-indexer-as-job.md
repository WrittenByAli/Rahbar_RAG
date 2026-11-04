# ADR 0001: Use the Indexer as a Kubernetes Job

## Status
Accepted · 2026-11-04

## Context
The RAHBAR API runs as a Deployment with 3 replicas, all reading from a single Chroma
StatefulSet backed by one PersistentVolumeClaim. If embedding and indexing ran inside
the API's startup path, every replica would attempt to extract, chunk, embed and upsert
the corpus on boot. Three concurrent writers to one Chroma instance create a data race:
partial writes from one replica can interleave with another, tripling wall-clock
indexing time and risking duplicate or corrupted chunks. Because Kubernetes may restart
pods at any time (rolling updates, node eviction, OOMKill), the race can repeat
unpredictably.

The problem is amplified by the embedding step, which is both slow and memory-intensive.
Running it inside the API container means the API process competes with the embedding
workload for CPU and memory, delaying readiness and risking OOMKill under the API's
tighter memory limit (512 Mi vs. the indexer's 2 Gi).

## Decision
The indexer is a standalone Kubernetes **Job** (`batch/v1`) defined in
`k8s/base/indexer-job.yaml`. It runs the pipeline (`python -m pipeline.run`), writes
chunks and embeddings to Chroma, records the embedding model name and vector dimension
in the collection metadata, and exits. The API Deployment is strictly read-only against
Chroma and never imports or runs any indexer code.

For index replacement we use a **delete-then-recreate** strategy: the indexer deletes
the existing collection, creates a fresh one with updated metadata, and upserts all
chunks. This is atomic from the API's perspective because the readiness probe
(`/readyz`) returns 503 while the collection is missing or empty, so Kubernetes removes
the pod from the Service endpoints until the new index is available.

A CronJob (`k8s/base/indexer-cronjob.yaml`) schedules periodic re-indexing with
`concurrencyPolicy: Forbid` to prevent overlapping runs.

## Options considered
1. **Index on API startup.** Rejected because 3 replicas race on one PVC and the API
   cannot serve traffic while indexing. See `api/app/main.py:30-43` — the lifespan
   function deliberately does not call any indexer code.
2. **Sidecar container in the API pod.** Rejected because it still shares the pod's
   memory limit and couples indexer lifecycle to API lifecycle.
3. **Init container.** Rejected because it delays pod readiness, does not retry on
   failure, and all 3 replicas still run it.

## Consequences
**Positive:**
- Safe to scale the API Deployment independently; adding replicas never triggers
  re-indexing.
- A single writer eliminates race conditions on Chroma.
- Kubernetes Job semantics (`backoffLimit: 3`, `restartPolicy: OnFailure`) handle
  transient failures automatically.
- The indexer can have generous resource limits (2 Gi memory) without inflating the
  API's resource footprint.

**Negative:**
- The index is stale between Job runs. Acceptable for a policy corpus that changes
  infrequently.
- Requires a separate container image build and Job invocation step in the deployment
  workflow.
- During delete-then-recreate, the API returns 503 until the new index is ready.
  Mitigated by the readiness probe removing pods from traffic.
