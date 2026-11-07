# Ali — Execution Plan

Written for the graders and Shahzad. This records what was planned for Ali's lane on
`feature/ali-rag-backend` and what was actually executed on 2026-11-08.

## Scope and ownership

Ali owns the backend/RAG lane: `corpus/`, `indexer/`, `api/`, `eval/`, and the app-level docs
(`CORPUS.md`, `PIPELINE.md`, ADRs for cache/provider, this report set). Shahzad owns `k8s/`,
`ui/`, `.github/workflows/`. Shared files (`docs/`, config contracts) change only with
coordination; no Shahzad-owned file was modified on this branch.

## Starting state (verified, not assumed)

- The implementation already existed on `dev` (pushed by the infra session) and CI was green,
  PR #1 (dev→main) open, `main` protected. Confirmed via `git`/`gh`.
- The real defects were **not** missing code but fabricated evidence: corpus manifest with the
  SHA-256 of the empty string, placeholder golden set, identical `baseline.json`/`results.json`,
  a dishonest `AI-USAGE.md`, and 8-byte placeholder evidence images.

## Plan → what was done

1. **Branch/identity hygiene** — work in the `Rahbar-Ali` worktree; commit as Ali
   (`programmerbusiness2@gmail.com`) via per-commit `--author` (the worktree's configured email
   was Shahzad's). DONE.
2. **Make the test suite real** — install deps, run it, raise coverage. 36 tests pass; API
   coverage 52%→92% via `api/tests/test_components.py`. DONE.
3. **Fix lint** — `ruff` clean; fixed 6 real `mypy` errors. DONE.
4. **Make the corpus real** — fetch from `nu.edu.pk`; real manifest with real checksums; verify
   the 7 properties (279 pages, image-only OCR doc, version pair, tables, long defs). DONE.
5. **Make the evaluation real** — pull `nomic-embed-text`; build `eval/offline_eval.py` (real
   chunk + real embeddings + brute-force cosine + real answer pipeline); run it; tune the
   relevance floor from measured scores; write honest `baseline.json`/`results.json`. DONE
   (fixtures).
6. **Make the docs honest** — rewrite `CORPUS.md`, `PIPELINE.md`, `AI-USAGE.md` to match real
   measurements; write this report set. DONE.
7. **Independent review** — a separate review pass over the diff. DONE (see final report).
8. **Deliver** — commit on `feature/ali-rag-backend`, push as Ali, open PR into `dev`. See
   final report for status.

## Explicitly out of scope on this machine (BLOCKED, not skipped)

Live Kubernetes (no minikube, Docker daemon down), so: cluster E2E, `kubectl top`/hpa/endpoints
evidence, rollout/HPA demos, CD build-push-deploy, and OCR execution (no tesseract/poppler).
These are documented with exact repro commands in `docs/ALI-FINAL-REPORT.md` rather than
fabricated.
