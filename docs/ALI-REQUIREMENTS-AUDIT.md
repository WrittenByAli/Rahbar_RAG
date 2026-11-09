# Ali — Requirements Audit (backend / RAG lane)

Written for the graders and for Shahzad, as a traceability record. Audited 2026-11-08 against
the assignment PDF and the actual repository on branch `feature/ali-rag-backend`. Status values:
**DONE** (implemented and verified here), **REAL-PARTIAL** (implemented; verified only as far
as this machine allows), **BLOCKED** (needs a cluster/infra not available on this machine),
**TODO** (genuine remaining work).

## Application code (Ali's lane)

| Requirement | File(s) | Status | Evidence |
|---|---|---|---|
| Indexer: extract (PDF/HTML/MD + OCR path) | `indexer/pipeline/extract.py` | REAL-PARTIAL | runs on text PDFs/HTML/MD; OCR path present but `tesseract`/`poppler` absent locally |
| Indexer: clean | `indexer/pipeline/clean.py` | DONE | unit tests pass |
| Indexer: structure-aware chunk + overlap | `indexer/pipeline/chunk.py` | DONE | tests pass; real chunk/amplification table in PIPELINE.md |
| Indexer: embed (pinned model, batched) | `indexer/pipeline/embed.py` | DONE | real `nomic-embed-text`, dim 768 |
| Indexer: store (Chroma, metadata, pin) | `indexer/pipeline/store.py` | REAL-PARTIAL | code correct; needs a Chroma server to exercise writes |
| API: ChromaRetriever (cosine, superseded filter) | `api/app/retrieval/chroma.py` | DONE | `test_chroma_retrieve_filters_superseded_and_scores` |
| API: semantic cache (Redis, invalidation, skip rules) | `api/app/services/cache.py` | DONE | 6 cache tests (hit/miss/semantic/skip/flush/cosine) |
| API: Ollama provider (JSON mode, retry, fallback) | `api/app/providers/llm/ollama.py` | DONE | 3 provider tests |
| API: Hosted provider | `api/app/providers/llm/hosted.py` | DONE | 2 provider tests |
| API: answer pipeline (floor, abstain, citation strip) | `api/app/services/answer.py` | DONE | starter + component tests |
| API: `/readyz` (count>0, embed-pin, redis) | `api/app/routes/health.py` | DONE | 3 readyz tests (mismatch/empty/ok) |
| API: `/healthz` touches nothing | `api/app/routes/health.py` | DONE | `test_liveness_answers_without_dependencies` |
| Embedding pin enforced in code | `health.py`, `main.py` | DONE | `test_readyz_503_on_embed_model_mismatch` |
| Relevance floor tuned from data | `api/app/config.py` | DONE | 0.30→0.55, measured scores in PIPELINE.md |
| Tests ≥12, injection + abstention | `api/tests/`, `indexer/tests/` | DONE | 36 tests; 92% API coverage |

## Corpus & evaluation (Ali's lane)

| Requirement | Status | Evidence |
|---|---|---|
| ≥6 docs, ≥40 pages, 7 properties | DONE | 9 docs, 279 pages; `docs/CORPUS.md`, real `corpus/MANIFEST.md` |
| Real SHA-256 manifest | DONE | replaced the fabricated empty-string hash |
| 3+ chunk configs measured | DONE | real amplification table (PIPELINE.md); fixture recall sweep |
| recall@3/@5, citation, abstention | DONE (fixtures) | `eval/results.json`: 1.0/1.0/1.0/1.0 via `eval/offline_eval.py` |
| Full-corpus golden set with real labels | TODO | `eval/golden.yaml` still placeholder; needs real sections after PDF heading fix |
| `eval/baseline.json` + `results.json` | DONE (fixtures, offline) | honest real run, method recorded in the files |

## Infra / CI / CD (Shahzad's lane — audited for integration)

| Item | Status | Note for Shahzad |
|---|---|---|
| CI green on `dev`, PR #1 open, `main` protected | DONE | verified via `gh` |
| CI e2e eval gate | BLOCKED/weak | `run_eval.py ... \|\| true` swallows the gate; dev overlay uses stub retriever |
| Live cluster, `kubectl top`/hpa/endpoints evidence | BLOCKED | minikube not installed, Docker daemon down on this machine |
| CD build+push to Docker Hub, deploy | BLOCKED | needs Docker + registry secrets |

See `docs/ALI-FINAL-REPORT.md` for the full honest status and the exact commands to close the
BLOCKED items on a real cluster.
