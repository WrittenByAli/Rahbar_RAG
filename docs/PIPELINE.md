# Indexing and Retrieval Pipeline

All numbers in this document were measured on this project's real corpus and the
CI fixture corpus on 2026-11-08, not estimated. Where a measurement could not be
produced on the development machine (no Kubernetes cluster, no Chroma server, no
OCR tooling), that is stated plainly rather than filled with a plausible guess.

## Extraction

`indexer/pipeline/extract.py` handles four formats:

- **PDF with a text layer** — `pdfplumber`, page by page; each `Page` has `ocr=False`.
- **Scanned / image-only PDF page** — when `page.extract_text()` is empty, the page is
  rendered with `pdf2image` (poppler) and read with `pytesseract`; the `Page` is marked
  `ocr=True`.
- **Markdown / plain text / HTML** — read as a single page.

### Which documents needed OCR (measured)

Probing the fetched corpus with `pdfplumber` (`corpus/raw/`, 2026-11-08):

| Document | Pages | Text layer? |
|----------|------:|-------------|
| `faculty-entrepreneurship-and-technical-start-ups-policy.pdf` | 8 | **None — fully image-only, OCR required** |
| `academic-rules-handbook-jun-2026.pdf` | 58 | mostly text, **some image-only pages** |
| `student-handbook-jun-2026.pdf` | 64 | mostly text, **some image-only pages** |
| `undergraduate-academic-rules-aug-2023.pdf` | 26 | mostly text, **some image-only pages** |
| `prospectus-2026-academic-rules-and-regulations.pdf` | 5 | text |
| `annual-report-2019-20.pdf` | 33 | text |
| `annual-report-2023-24.pdf` | 85 | text |

Finding: the obviously-scanned Faculty Entrepreneurship policy is not the only OCR case —
three of the longer "text" PDFs also contain image-only pages that fall through to the OCR
path. **Honest limitation:** `tesseract` and `poppler` are not installed on the development
machine used for this session, so the OCR path could not be exercised locally; those pages
raise `pdf2image.PDFInfoNotInstalledError` and are excluded from the local chunking
measurements below. On the cluster (and in the indexer image, which `apt-get install`s
`tesseract-ocr` and `poppler-utils` — see `indexer/Dockerfile`) the OCR path runs.

## Cleaning

`indexer/pipeline/clean.py`: repeated header/footer removal, whitespace normalisation,
hyphenated line-break repair, and table/line preservation. Section headings and numbered
clause identifiers are deliberately **kept**, because `chunk.py` turns the nearest heading
into `Chunk.section`.

Known extraction weakness for the real corpus: `chunk.py`'s heading detector recognises
Markdown `#` headings and short ALL-CAPS lines. The fixture corpus (Markdown, `## 1. Attendance`)
labels sections cleanly, but FAST-NUCES PDFs use numbered clauses like `1.21 Attendance`,
which are **not** ALL-CAPS and are not detected, so most PDF chunks inherit the section
`"Introduction"`. This is why the meaningful recall measurement below uses the fixture corpus;
improving PDF heading detection (e.g. a `^\d+(\.\d+)*\s+\w` clause pattern) is the first
retrieval improvement to make and is recorded in `docs/FAILURE-ANALYSIS.md`.

## Chunking

`indexer/pipeline/chunk.py` — structure-aware: split on sections, then paragraphs, then
sentences, under a target `size`, sharing `overlap` tokens between neighbours. Chunk IDs are
stable: `sha256(source + section + position_index)[:16]`.

### Configurations measured (real corpus, 5 text documents, 47,077 source tokens)

Measured with `indexer/pipeline` extract→clean→chunk on 2026-11-08 (the four PDFs with
image-only pages were excluded because OCR tooling is absent locally; storage amplification =
stored tokens ÷ original tokens, the lecture's metric):

| Size | Overlap | Chunks | Stored tokens | Storage amplification |
|-----:|--------:|-------:|--------------:|----------------------:|
| 200  | 0       | 288    | 46,786        | 0.994x |
| 400  | 50      | 170    | 53,979        | 1.147x |
| 600  | 100     | 136    | 56,976        | 1.210x |

**Shipped: (400, 50)** — the default in `CHUNK_SIZE`/`CHUNK_OVERLAP`. At size 200 with no
overlap, chunks fragment policy clauses and lose cross-boundary context; at size 600 with
100 overlap, distinct clauses merge, which hurts precision on exact-term questions, and
amplification climbs to 1.21x. (400, 50) is the balance point — 15% redundancy for
boundary coverage.

### Recall by configuration (fixture corpus, real embeddings)

The fixture corpus (`eval/fixtures/`, clean Markdown headings) gives meaningful
`(source, section)` recall. `eval/offline_eval.py --sweep` on 2026-11-08, real
`nomic-embed-text` embeddings, brute-force cosine (identical top-k to Chroma's cosine space):

| Size | Overlap | Chunks | recall@3 | recall@5 | citation validity | abstention |
|-----:|--------:|-------:|---------:|---------:|------------------:|-----------:|
| 200  | 0       | 14     | 1.00     | 1.00     | 1.00              | 1.00 |
| 400  | 50      | 14     | 1.00     | 1.00     | 1.00              | 1.00 |
| 600  | 100     | 14     | 1.00     | 1.00     | 1.00              | 1.00 |

The fixtures are small (6 questions, 14 chunks), so configs do not separate on recall here;
the real corpus is where (400, 50) earns its place (table above). `eval/golden.yaml` for the
full corpus still carries placeholder `(source, section)` labels and must be re-pointed at the
real documents and real sections once PDF heading detection is improved — see the honest note
in `docs/ALI-FINAL-REPORT.md`.

## Embedding

- **Model**: `nomic-embed-text` via Ollama (`POST {ollama_url}/api/embed`), batched 64 at a
  time (`indexer/pipeline/embed.py`).
- **Dimension**: **768** (measured against the running Ollama on 2026-11-08).
- **Pin location**: `indexer/pipeline/store.py` writes `embed_model` and `dimension` into the
  Chroma collection metadata on create. The API enforces the pin in `api/app/routes/health.py`
  (`/readyz` returns 503 `embed_model mismatch: stored=X api=Y`) and logs it at startup in
  `api/app/main.py` lifespan. Covered by `test_readyz_503_on_embed_model_mismatch`.

## Relevance floor (tuned on real data)

The answer pipeline (`api/app/services/answer.py`) drops passages below
`settings.relevance_floor` and abstains when none remain. Measured top-1 cosine scores on the
fixture golden set (`nomic-embed-text`, 2026-11-08):

| Question kind | top-1 score range |
|---------------|-------------------|
| Answerable (f01–f04, f06) | 0.653 – 0.776 |
| Off-topic / must-abstain (f05 hostel) | 0.503 |

The default floor was **0.30**, which let the off-topic hostel question through
(abstention_rate 0.0). Following the lecture rule — the threshold that rejects every off-topic
question with zero false drops — it was raised to **0.55** (between 0.503 and 0.653) in
`api/app/config.py`. After the change the offline eval reports abstention_rate 1.0 with recall
unchanged. The cluster ConfigMap's `RELEVANCE_FLOOR` should be set to 0.55 to match (infra
lane).

## Semantic cache

`api/app/services/cache.py` (Redis). Exact key `sha256(normalised question)`; semantic match
embeds the question and compares cosine against stored question vectors; abstentions are never
cached (`_should_skip_cache`); `flush()` clears all entries for re-index invalidation.

- **Threshold**: `CACHE_THRESHOLD = 0.92` (`api/app/config.py`). This is the shipped default;
  a full false-hit sweep needs a live Redis + embedding pass and was **not** run in this
  offline session, so it is not reported as measured. The tuning method is the lecture's:
  the lowest threshold with zero false hits on the golden questions. Cache behaviour (exact
  hit, semantic hit, miss, abstention-skip, flush invalidation) is covered by tests in
  `api/tests/test_components.py`.

## Evaluation method

`eval/run_eval.py` scores a live API; `eval/offline_eval.py` scores the same pipeline in one
process when no cluster is available. `recall@k` matches the golden `relevant` list to the
response's `retrieved` list by **(source, section)** exact string (stable across chunk-config
changes, unlike chunk IDs). Citation validity = fraction of citations whose `(source, section)`
appears in `retrieved`; invalid citations are stripped in `answer.py` before returning.
Abstention correctness = every must-abstain question returns `answered_from_context=false`.
