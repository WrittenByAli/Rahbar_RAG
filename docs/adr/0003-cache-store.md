# ADR 0003: Redis for the Semantic Cache

## Status
Accepted · 2026-11-04

## Context
Generating an answer via an LLM (Ollama or a hosted provider) takes 2–10 seconds per
question. Many users ask similar or identical questions, especially during exam periods
when students look up the same attendance or GPA policies. Without caching, every
repeated question pays the full retrieval-and-generation cost, wastes GPU cycles, and
increases tail latency.

A semantic cache stores previous answers keyed by question similarity, so that a
question close enough to a previously answered one can return the cached response
instantly. The design requires:

1. Fast key-value lookups (hash-based exact match).
2. Vector similarity search for semantic matching (cosine similarity threshold).
3. TTL-based expiration.
4. Cache invalidation when the index is rebuilt (generation ID mismatch).

## Decision
We use **Redis** (`redis:7.2-alpine`) as the cache backing store, deployed as a
Kubernetes Deployment with a ClusterIP Service (`k8s/base/redis-deployment.yaml`,
`k8s/base/redis-service.yaml`). The cache logic lives in `api/app/services/cache.py`.

The cache operates in two tiers:

1. **Exact match**: `key = sha256(normalized_question)`, value = serialized
   `AskResponse` JSON. O(1) lookup.
2. **Semantic match**: the question's embedding vector is compared against stored
   question vectors using cosine similarity. If the best match exceeds
   `cache_threshold` (default 0.92, configured in `api/app/config.py`), the cached
   response is returned.

Cache invalidation:
- A `generation_id` is stored in the ConfigMap. The cache stores the generation ID with
  each entry. On retrieval, if the stored generation ID does not match the current one,
  the entry is treated as a miss and evicted.

Rules for what is never cached:
- Abstentions (`answered_from_context=False`): caching a non-answer would suppress
  future attempts that might succeed after re-indexing.
- Follow-up questions: detected by question length < 10 words or presence of pronouns
  without prior context.

We tried several similarity thresholds:
- **0.85**: too aggressive — "What is the GPA requirement?" matched "What is the fee
  structure?" (both start with "What is the..."). The false hit returned fee data for
  a GPA question. Documented in `docs/PIPELINE.md`.
- **0.95**: too conservative — slight rephrasings ("What's the attendance policy?" vs.
  "What is the attendance policy?") were cache misses.
- **0.92**: the sweet spot. No false hits observed in our golden set.

## Options considered
1. **Store cache entries in Chroma alongside retrieval chunks.** Rejected — mixing
   cache and retrieval data in one collection creates coupling, complicates the
   superseded filter, and makes cache invalidation require touching the retrieval
   index.
2. **In-process LRU cache (e.g., `functools.lru_cache`).** Rejected — with 3 API
   replicas, each replica has its own cache, tripling memory usage and reducing hit
   rate.
3. **Memcached.** Viable but lacks native TTL granularity per key and has no built-in
   data structures for storing vectors alongside responses. Redis is the more natural
   fit.

## Consequences
**Positive:**
- Sub-millisecond cache hits for repeated questions.
- Reduces LLM load during peak usage periods.
- Clean separation: Chroma for retrieval, Redis for caching.
- TTL and generation-ID invalidation keep the cache fresh.

**Negative:**
- Adds Redis as an infrastructure dependency.
- Semantic matching requires embedding the incoming question even for cache lookups
  (mitigated: the embedding is needed for retrieval anyway).
- Cache entries consume Redis memory; bounded by TTL and explicit eviction.
