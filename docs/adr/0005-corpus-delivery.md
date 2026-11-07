# ADR 0005: Deliver the real corpus to the indexer via an init container

## Status
Accepted · 2026-11-08

## Context
`indexer/Dockerfile` only `COPY`s `pipeline/`; it never bakes in `corpus/raw/`, which is
gitignored (the documents are downloaded from FAST-NUCES at runtime by `corpus/fetch.py`,
not committed). Neither `indexer-job.yaml` nor `indexer-cronjob.yaml` mounted anything for
`CORPUS_DIR` (default `/corpus`) — only a `tmp` emptyDir existed. `run_pipeline()` in
`indexer/pipeline/run.py` raises `SystemExit` immediately if `discover(settings.corpus_dir)`
finds nothing, so the real (non-`--dummy`) indexer path had no way to find any documents at
all. Both indexer containers also run with `readOnlyRootFilesystem: true`, so whatever
delivers the corpus must write only to a mounted volume, never the container's own
filesystem.

## Decision
An **init container** in `indexer-cronjob.yaml` (the periodic real-reindex path; the
one-time `indexer-job.yaml` stays `--dummy`-only for week-1 testing) runs the real,
unmodified `corpus/fetch.py` against the real, unmodified `corpus/sources.yaml`:

1. `make corpus-scripts` packages those two files — read, not duplicated or edited — into
   a `corpus-fetch-scripts` ConfigMap, the same imperative pattern this project already
   uses for `make secret` (so it never needs to go through `kustomize`'s
   `configMapGenerator`, which refuses to read files outside `k8s/base/` without weakening
   its default load-restrictor for every manifest build, including the CI `kubeconform` job).
2. The init container reuses the **indexer image itself** (`rahbar-indexer:dev`), which
   already has `httpx`/`pyyaml` installed for `requirements.txt` — no new image, no
   `pip install` at pod start. It copies the two scripts from the read-only ConfigMap mount
   into the `tmp` emptyDir (writable), runs `fetch.py` there (`HERE` resolves to `tmp` via
   `__file__`, so `raw/` lands at `tmp/raw/`), then copies just the downloaded documents
   into a new `corpus-data` emptyDir.
3. The main `indexer` container mounts `corpus-data` **read-only** at `/corpus`; `discover()`
   finds `_index.json` there (written by `fetch.py`) and proceeds normally.
4. Both the init and main containers needed `app: indexer` added to the pod template labels
   and a new `allow-indexer` NetworkPolicy — the default-deny policy blocks all egress by
   default, and there was previously no rule granting indexer pods egress to Chroma, Ollama,
   DNS, or the public internet at all. This had gone unnoticed because CI's `kind` cluster
   uses the default `kindnet` CNI, which does not enforce NetworkPolicies; only a real
   NetworkPolicy-enforcing cluster (this project's own `make cluster`, which sets
   `--cni=calico`) would have ever hit it.

## Options considered
1. **Bake the corpus into the indexer image at build time.** Rejected: ties a content
   change (a new policy document) to an image rebuild/push, and risks the "corpus
   generated/bundled wrong" mistake the assignment explicitly warns about — the real
   download-and-hash step (`corpus/fetch.py` + `MANIFEST.md`) is the actual provenance
   record; baking in `corpus/raw/` would bypass it for the in-cluster copy.
2. **hostPath volume into minikube.** Rejected: not portable to any other cluster, and
   specifically breaks CI's `kind` cluster, which has no such host path — would need a
   second, divergent mechanism just for CI.
3. **Init container running the real fetch script (chosen).** Reuses the exact same
   download/verification code used for local development, keeps `corpus/raw/` out of every
   image, and works identically in `kind` and in minikube.

## Consequences
**Positive:**
- One real corpus-provenance path, not two to keep in sync.
- No image rebuild needed when the corpus changes — only a re-run of the CronJob.
- `corpus/fetch.py` and `corpus/sources.yaml` are referenced, never duplicated; no drift risk.

**Negative:**
- Every real reindex re-downloads the full corpus (no caching across runs); acceptable at
  this corpus size and `concurrencyPolicy: Forbid` scheduling.
- The init container needs broad `ipBlock: 0.0.0.0/0` egress on ports 80/443, since the
  university's own IP ranges aren't known in advance — narrower than nothing, but not
  narrowed to a specific CIDR.
- CI's `e2e` job does not exercise this path at all (it indexes the fixture corpus
  differently, see the eval-gate discussion elsewhere); the init container is only
  validated by manifest rendering/schema checks, not a live run, until someone runs it on a
  real cluster.
