# AI Usage Disclosure

The assignment's rule is honest attribution, not avoidance. This document is written to be
accurate about what AI tools did and did not do, so the submission reflects work the authors
can explain. Where earlier drafts of this file overstated manual verification, this version
corrects it.

## Tools used

- **Claude Code** (Anthropic), models **Claude Opus** and **Claude Sonnet**, used as a coding
  assistant and orchestrator from the command line.

## What AI generated

- The initial implementation of the indexer pipeline stages (`extract`, `clean`, `chunk`,
  `embed`, `store`), the API components (`ChromaRetriever`, semantic cache, Ollama/Hosted
  providers, the answer pipeline, `/readyz`), the Kubernetes manifests, the Dockerfiles, the
  CI/CD workflows, the four ADRs, and the first drafts of the documentation.
- The additional API component tests in `api/tests/test_components.py`.
- The offline evaluator `eval/offline_eval.py`.

## What was actually run and verified in this session (2026-11-08)

These are real, reproducible actions, not claims:

- **Dependencies installed** into a local `.venv`; the full test suite run: **27 API tests +
  9 indexer tests pass**. API coverage measured at **92%** (was 52% before the new tests);
  indexer 63%.
- **Lint**: `ruff` clean; `mypy` clean after fixing 6 real type errors in `cache.py` and
  `chroma.py`.
- **Real corpus fetched** with `corpus/fetch.py` from `nu.edu.pk`: 9 documents, ~35 MB, 279
  PDF pages. `corpus/MANIFEST.md` now carries **real SHA-256 checksums** (an earlier version
  contained the SHA-256 of the empty string — a fabricated placeholder — which has been
  replaced).
- **Corpus properties verified** by probing the files: one fully image-only PDF (OCR case),
  three more PDFs with image-only pages, the two-version policy pair, tables (fees/grading/
  annual reports), long definitions (64-page handbook), 279 pages total.
- **Real embeddings**: `nomic-embed-text` pulled via Ollama and used to embed chunks and
  queries (dimension 768 confirmed).
- **Real offline evaluation** (`eval/offline_eval.py`) on the fixture corpus: recall@3 = recall@5
  = 1.0, citation validity = 1.0, abstention = 1.0. `eval/results.json` and `eval/baseline.json`
  reflect this real run.
- **Relevance floor tuned from measured data** (0.30 → 0.55) after observing answerable
  questions score 0.65–0.78 and the off-topic question 0.50.
- **Real chunking/storage-amplification table** measured on the real corpus (see
  `docs/PIPELINE.md`).

## What was NOT done, and is stated honestly rather than fabricated

- No Kubernetes cluster was available on the development machine (minikube not installed,
  Docker daemon down), so the live-cluster evaluation, the `kubectl top`/`get hpa`/
  `get endpoints` evidence, the rollout/HPA demos, and the CD deploy were **not** produced
  locally. The evidence files for these are placeholders; see `docs/ALI-FINAL-REPORT.md` for
  the exact BLOCKED items and the commands a grader would run on a real cluster.
- OCR was not exercised locally (`tesseract`/`poppler` absent); it runs in the indexer image.
- `eval/golden.yaml` (full-corpus golden set) still uses placeholder `(source, section)` labels
  and needs re-pointing at the real documents once PDF heading detection is improved.

## Author responsibility

The authors (Ali, Shahzad) are responsible for understanding and being able to explain every
part of this submission. AI was used to write and run code faster; it does not replace that
understanding, and the viva is where it is demonstrated.
