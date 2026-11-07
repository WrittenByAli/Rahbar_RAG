# ADR 0002: Structure-Aware Chunking Over Fixed Windows

## Status
Accepted · 2026-11-04

## Context
The RAHBAR indexer must split university policy documents into chunks small enough for
embedding and retrieval, yet large enough to preserve the context a reader needs to
answer a question. Policy documents from FAST-NUCES have clear structural markers:
numbered sections (`## 5.4 Academic Warning`), paragraphs, and enumerated clauses. A
chunking strategy that ignores this structure — for example, a fixed sliding window of
N tokens — splits mid-clause, separates a heading from its body, and produces chunks
whose boundaries are arbitrary. When a retriever returns such a chunk the LLM receives
a sentence fragment, cannot identify the policy section, and either hallucinates
context or abstains unnecessarily.

The chunking step must also produce stable chunk IDs (so Chroma upserts are idempotent)
and carry metadata (`source`, `section`, `page`, `doc_version`, `superseded`) that the
API's citation logic and superseded-document filter depend on.

## Decision
We implemented structure-aware chunking in `indexer/pipeline/chunk.py`:

1. **Split on headings** (`##` or lines that look like section titles). Each heading
   starts a new section; the heading text becomes `Chunk.section`.
2. **Split on paragraphs** within each section (double newline).
3. **Split on sentences** within a paragraph if it still exceeds `size` tokens.
4. **Overlap**: the last `overlap` tokens of one chunk are prepended to the next,
   preserving cross-boundary context.
5. **Chunk ID**: `sha256(source + section + position_index)[:16]` — deterministic and
   stable across re-runs of the same document version.

We measured three `(size, overlap)` configurations against `recall@5` on our golden set
(see `docs/PIPELINE.md` for the full table):

| Size | Overlap | recall@5 | Chunks |
|------|---------|----------|--------|
| 300  | 30      | 0.72     | 187    |
| 400  | 50      | 0.82     | 142    |
| 500  | 75      | 0.78     | 118    |

We selected **(400, 50)** as the default (`CHUNK_SIZE=400`, `CHUNK_OVERLAP=50` in the
ConfigMap). It achieves the best recall while keeping chunk count manageable. The 500/75
configuration produced larger chunks that diluted similarity scores for narrow factual
questions (exact CGPA thresholds, fee amounts).

## Options considered
1. **Fixed sliding window (no structure awareness).** Rejected — splits mid-clause,
   loses section metadata, degrades retrieval for section-specific questions.
2. **Recursive character text splitter (LangChain-style).** Considered, but it treats
   all separators equally. Our hierarchy (headings > paragraphs > sentences) is
   explicit and produces better section assignments.
3. **One chunk per page.** Rejected — pages are too large for embedding models, and
   page boundaries do not align with topic boundaries.

## Consequences
**Positive:**
- Chunks align with policy sections, making citations meaningful.
- Headings are preserved as `Chunk.section`, enabling the retrieval filter and
  evaluation matching by `(source, section)`.
- Overlap mitigates information loss at chunk boundaries.

**Negative:**
- The chunking logic is more complex than a fixed window.
- Very short sections produce small chunks that may rank lower by similarity.
- Changes to document formatting (e.g., inconsistent heading styles) require updating
  the heading detection heuristic.
