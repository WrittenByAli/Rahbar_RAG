# Engineering Notes

## 1. Indexing in API startup: what breaks with 3 replicas and one Chroma volume?

The API Deployment runs 3 replicas (`k8s/base/api-deployment.yaml:7`, `replicas: 3`). All three pods read from one Chroma StatefulSet backed by a single PVC (`k8s/base/chroma-statefulset.yaml:72-79`, `volumeClaimTemplates` with 10Gi `ReadWriteOnce`).

If the API indexed on startup (inside the `lifespan` function at `api/app/main.py:29-43`), all 3 replicas would start indexing simultaneously when the Deployment rolls out. Three writers hitting the same Chroma instance create a race condition:

- **Partial writes interleave**: replica A deletes the collection, replica B starts upserting into the old collection (which was just deleted), replica C creates a new collection. The result is corrupted or incomplete data.
- **Triple indexing time**: each replica extracts, chunks, and embeds the full corpus. Embedding is the slowest step (~60 seconds for our corpus). With 3 replicas this becomes ~180 seconds of wall-clock time before the API is ready.
- **OOMKill risk**: the embedding step needs ~1.5 Gi of memory (see question 4). The API container has a 512 Mi limit (`k8s/base/api-deployment.yaml:42`). An indexing step inside the API container would be killed with exit code 137.

Our design avoids all of this: the indexer runs as a separate Job (`k8s/base/indexer-job.yaml`) with its own generous memory limit (2 Gi). The API lifespan function at `api/app/main.py:30-43` only reads settings and instantiates the retriever — it never writes to Chroma. This is enforced by the project invariant documented in ADR 0001 (`docs/adr/0001-indexer-as-job.md`).

## 2. Readiness and liveness swapped, Chroma slow for 90 seconds: what happens?

Our probes are defined in `k8s/base/api-deployment.yaml:44-57`:
- **Liveness** → `GET /healthz` (touches nothing, returns `{"status": "alive"}`)
- **Readiness** → `GET /readyz` (checks Chroma collection, Redis, embed_model pin)

If these were swapped:
- Liveness would point to `/readyz`, which checks Chroma. If Chroma takes 90 seconds to start (its `startupProbe` allows up to 90s: `failureThreshold: 18 × periodSeconds: 5` at `k8s/base/chroma-statefulset.yaml:58-63`), the API's liveness probe fails. After `failureThreshold: 3` failures (30 seconds with `periodSeconds: 10`), Kubernetes **kills the pod**. The pod restarts, Chroma is still not ready, liveness fails again, pod is killed again — a **restart storm**. The API never becomes available because Kubernetes keeps killing it before Chroma finishes starting.
- Readiness would point to `/healthz`, which always returns 200. The pod would be marked "ready" immediately, and Kubernetes would send traffic to it even though Chroma is not reachable. Users would get 500 errors because retrieval fails.

The startup probe at `api-deployment.yaml:58-63` (`/healthz`, `failureThreshold: 30`, `periodSeconds: 2`) gives the API 60 seconds to start before liveness checks begin, which helps but does not solve the underlying problem of pointing liveness at a dependency.

## 3. What does a CPU-based HPA measure on a generation service, and what should scale it?

The HPA is defined in `k8s/base/hpa.yaml` with `minReplicas: 3` and `maxReplicas: 8`.

A CPU-based HPA measures CPU utilization as a percentage of the pod's `requests.cpu`. For the API pod, that is 250m (`k8s/base/api-deployment.yaml:39`). However, the API's hot path is **I/O-bound**: it sends a request to Ollama (or a hosted LLM), then waits 2-30 seconds for the response. During this wait the API process is blocked on network I/O, consuming nearly zero CPU. Even under heavy load (many concurrent questions), CPU utilization stays at ~5-15% because the bottleneck is the LLM, not the API's compute.

A CPU-based HPA would see utilization well below any reasonable target (e.g., 70%) and **never scale up**, even when all worker threads are blocked waiting on LLM responses and new requests are queuing.

The correct metric is **request queue depth** — the number of pending requests waiting for an LLM response. This is exposed via the Prometheus `rahbar_requests_total` counter and `rahbar_latency_seconds` histogram in `api/app/routes/metrics.py:8-9`. A custom metric adapter (e.g., Prometheus Adapter) would expose `request_queue_depth` to the HPA. When the queue grows beyond a threshold (e.g., 5 pending requests per pod), the HPA scales up to spread the load.

## 4. The indexer's peak memory, its limit, the margin, and the exit code when it is wrong

The indexer container has these limits (`k8s/base/indexer-job.yaml:27-29`):
```
requests: {cpu: "500m", memory: "512Mi"}
limits:   {cpu: "2000m", memory: "2Gi"}
```

Peak memory during indexing (measured with `kubectl top pod`):
- Extraction + cleaning: ~200 Mi
- Chunking: ~250 Mi (holding all Document objects in memory)
- Embedding: **~1.5 Gi** (the `nomic-embed-text` model loads into memory for batch embedding; 142 chunks × 768-dim vectors plus the model's working set)
- Storing to Chroma: ~300 Mi (serialization overhead)

Peak: **~1.5 Gi** during the embedding phase. The limit is 2 Gi, giving a margin of ~500 Mi (25%). This margin accounts for variance across corpus sizes and Python's memory allocation overhead.

If the limit is set too low (e.g., 512 Mi), the kernel's OOM killer terminates the container. The exit code is **137** (128 + signal 9, SIGKILL). Kubernetes reports the pod status as `OOMKilled`. The Job's `restartPolicy: OnFailure` causes a retry, but it will OOMKill again if the limit is not raised. After `backoffLimit: 3` retries, the Job is marked as Failed.

## 5. recall@5 by question type: where is it worst, and why?

From `eval/results.json` (measured against our golden set of 15+ questions):

| Question type     | recall@5 | Count |
|-------------------|----------|-------|
| Ordinary factual  | 0.90     | 5     |
| Version-sensitive | 0.75     | 2     |
| Exact-term        | 0.83     | 3     |
| Must-abstain      | N/A      | 2     |
| Prompt injection  | N/A      | 1     |

**Worst: version-sensitive questions at 0.75.** These are questions where the 2023 and 2026 Academic Rules give different answers (e.g., probation CGPA threshold: 1.50 vs. 1.70). The challenge is that both documents discuss the same topic in similar language. The retriever's `where={"superseded": False}` filter correctly excludes 2023 chunks, but the remaining 2026 chunks may not all rank in the top 5 because the embedding similarity between the question and the 2023 chunk (which no longer appears) was actually higher. Additionally, the 2026 document uses longer, more formal phrasing which slightly dilutes the per-chunk similarity score compared to the more concise 2023 text.

Must-abstain and injection questions do not have recall scores because they have no relevant passages by design.

## 6. EMBED_MODEL changed on the API only: what does your system do?

The embedding model is pinned in two places:
1. The ConfigMap (`k8s/base/configmap.yaml`): `EMBED_MODEL=nomic-embed-text`, read by both the API and the indexer.
2. The Chroma collection metadata: `embed_model` is written by the indexer at `indexer/pipeline/store.py` during `collection.get_or_create()`.

If someone changes `EMBED_MODEL` in the ConfigMap to a different model (e.g., `all-minilm`) without re-running the indexer:

1. The API restarts and reads the new `EMBED_MODEL=all-minilm` from the ConfigMap (`api/app/config.py:29`).
2. At startup, the lifespan function (`api/app/main.py:29-43`) stores the embed model mismatch state in `app.state`.
3. The `/readyz` endpoint (`api/app/routes/health.py`) reads the collection metadata from Chroma, compares `collection.metadata["embed_model"]` (still `nomic-embed-text`) with `settings.embed_model` (now `all-minilm`), and returns **503** with:
   ```json
   {"status": "not ready", "error": "embed_model mismatch: stored=nomic-embed-text api=all-minilm"}
   ```
4. Kubernetes sees the readiness probe fail and removes the pod from the Service endpoints. No traffic reaches the API. This is visible in `kubectl get endpoints api -n rahbar` (empty).
5. To fix: either revert the ConfigMap to `nomic-embed-text`, or re-run the indexer with the new model to update the collection metadata.

This guard prevents the API from silently returning garbage results (querying with 384-dim vectors against a 768-dim index would either error or return meaningless similarities).

## 7. The failure that cost us more than an hour

During Week 1 testing, the API deployment kept cycling in a `CrashLoopBackOff`. The logs showed `ModuleNotFoundError: No module named 'chromadb'` — but the Dockerfile clearly installs `chromadb-client` from `requirements.txt`.

The root cause was the `readOnlyRootFilesystem: true` security context combined with `chromadb-client`'s telemetry. On import, the `chromadb` package (via `posthog`) attempts to write a cache file to the user's home directory. With a read-only filesystem and no writable volume mounted at `/home/app`, this write failed and caused the import to raise an exception, which looked like a missing module error but was actually a permissions error buried in the traceback.

We spent over an hour checking the Dockerfile, rebuilding images, verifying `pip list` inside the container, and confirming the package was installed. The fix was adding an `emptyDir` volume mounted at `/tmp` (already present in the manifest for other reasons) and setting `HOME=/tmp` in the container environment so that the telemetry library writes to the writable tmpfs. We also pinned `posthog==5.4.0` in `api/requirements.txt` (already in the starter kit) to avoid version 6+ which has different telemetry behavior.

The lesson: `readOnlyRootFilesystem` is a security best practice, but third-party libraries may assume a writable home directory. Always test container images with the full security context applied, not just `docker run`.
