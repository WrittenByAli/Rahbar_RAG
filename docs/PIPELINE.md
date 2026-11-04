# Indexing and Retrieval Pipeline

## Extraction

The extraction stage (`indexer/pipeline/extract.py`) handles four file formats:

- **PDF with text layer**: uses `pdfplumber` to extract text page by page. Each page becomes a `Page` object with `ocr=False`.
- **Scanned PDF (image-only)**: when `page.extract_text()` returns empty or None, the page is converted to an image using `pdf2image` (requires `poppler-utils`) and then OCR'd with `pytesseract`. These pages are marked `ocr=True`.
- **Markdown / plain text**: read as a single page.
- **HTML**: read with basic tag stripping as a single page.

### Documents that needed OCR

The Attendance Policy PDF (`Attendance_Policy_Scanned.pdf`) had no text layer on any of its 6 pages. All pages were processed through the OCR path.

Before/after example (page 1, paragraph 2):

| Stage | Text |
|-------|------|
| Raw OCR output | `Studcnts are rcquired to maintaln a minimum of 8O% attendancc in each coursc.` |
| After cleaning | `Students are required to maintain a minimum of 80% attendance in each course.` |

The Fee Schedule's Table 2.1 had merged header cells that `pdfplumber` extracted as a single concatenated string. The cleaning stage split it using whitespace heuristics, but one sub-header ("Lab Fee Component") was lost. This is documented in `docs/CORPUS.md`.

## Cleaning

The cleaning stage (`indexer/pipeline/clean.py`) applies these rules in order:

1. **Header/footer removal**: detect lines that repeat identically on 3 or more consecutive pages. Remove them. This catches running headers ("FAST-NUCES Academic Rules") and footers ("Page X of Y", "Confidential").
2. **Whitespace normalization**: collapse runs of 3+ newlines to 2; collapse runs of 2+ spaces to 1.
3. **Hyphenated line-break repair**: join lines ending in `-` followed by a lowercase letter on the next line (e.g., `atten-\ndance` becomes `attendance`).
4. **Table structure preservation**: lines containing `|` or tab-aligned columns are kept as-is. Tables are preserved as pipe-delimited ASCII text so they survive chunking.
5. **Section headings preserved**: lines matching heading patterns (`## N.N Title`, `Section N:`, all-caps short lines) are kept intact because they become `Chunk.section`.

Deliberately not stripped: section headings and numbered clause identifiers. The chunking stage depends on these to assign `Chunk.section` and to split at natural boundaries.

## Chunking

Implemented in `indexer/pipeline/chunk.py`. Structure-aware, three-level split:

1. Split on `##` headings (or detected section boundaries).
2. Within a section, split on paragraph boundaries (double newline).
3. Within a paragraph, split on sentence boundaries if it still exceeds `size` tokens.

Overlap: the last `overlap` tokens of chunk N are prepended to chunk N+1.

Chunk IDs are stable: `sha256(source + section + position_index)[:16]`.

### Configurations measured

| Size (tokens) | Overlap (tokens) | recall@5 | Chunks stored | Storage amplification |
|---------------|-------------------|----------|---------------|-----------------------|
| 300           | 30                | 0.72     | 187           | 1.31x                 |
| 400           | 50                | 0.82     | 142           | 1.18x                 |
| 500           | 75                | 0.78     | 118           | 1.12x                 |

**Selected**: (400, 50) — best recall@5 at 0.82. The 300-token config produced too many small chunks, diluting context. The 500-token config merged distinct policy clauses into single chunks, reducing retrieval precision for narrow factual questions (e.g., exact CGPA thresholds).

Storage amplification = total stored tokens / original document tokens. The overlap introduces ~18% redundancy at (400, 50).

## Embedding

- **Model**: `nomic-embed-text` via Ollama (`POST {ollama_url}/api/embed`)
- **Dimension**: 768
- **Pin location**: the collection metadata stores `embed_model` and `dimension` (written by `indexer/pipeline/store.py`). The API checks this in `/readyz` (`api/app/routes/health.py`) and at startup in `api/app/main.py` lifespan. A mismatch returns 503 with `embed_model mismatch: stored=X api=Y`.
- **Batching**: all chunk texts are sent in a single request to Ollama's `/api/embed` endpoint (the `input` field accepts a list). For corpora exceeding 256 texts, we batch in groups of 256.

## Semantic Cache

Implemented in `api/app/services/cache.py` using Redis.

- **Exact match**: `sha256(normalized_question)` as key.
- **Semantic match**: embed the question, compare against stored question vectors with cosine similarity.
- **Threshold**: 0.92 (configured via `CACHE_THRESHOLD` in `api/app/config.py`).

Thresholds tried:

| Threshold | Result |
|-----------|--------|
| 0.85      | False hit: "What is the GPA requirement?" matched "What is the fee structure?" — both start with "What is the..." but the answer was about fees, not GPA. **Rejected.** |
| 0.92      | No false hits observed. Slight rephrasings ("What's the attendance policy?" vs. "What is the attendance policy?") correctly match. **Shipped.** |
| 0.95      | Too conservative. Rephrasings were cache misses, defeating the purpose. |

Never cached: abstentions (`answered_from_context=False`) and responses where the question has fewer than 4 words.

Cache invalidation: a `generation_id` is stored with each cache entry. On re-index the generation ID in the ConfigMap changes, and stale entries are treated as misses.

## Evaluation Method

`eval/run_eval.py` computes `recall@k` by matching retrieved passages to the golden set's `relevant` list. Matching is by **(source, section)** — exact string match after stripping leading/trailing whitespace. This was chosen over chunk-ID matching because chunk IDs change when the chunking configuration changes, but source and section names are stable properties of the document.

Citation validity checks that every `Citation` in the response has a matching `(source, section)` pair in the `retrieved` list. A citation that references a passage not in the top-k retrieval is invalid and is stripped by the answer service before returning.
