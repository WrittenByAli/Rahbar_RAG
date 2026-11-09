# Corpus

Source: FAST-NUCES public website (`nu.edu.pk`). Documents: **9** (7 PDF + 2 HTML).
PDF pages: **279** (plus 2 HTML pages). Fetched on 2026-11-08 with `corpus/fetch.py`; every
file's URL, byte size and real SHA-256 are recorded in `corpus/MANIFEST.md`. The PDFs are not
committed (they are third-party; `corpus/raw/` is gitignored) — the manifest and the fetch
script reproduce them. Page counts and text-layer status below were measured with `pdfplumber`,
not estimated.

## Document inventory

1. **Undergraduate Academic Rules (Aug 2023)** — `undergraduate-academic-rules-aug-2023.pdf`,
   26 pages, `doc_version: 2023-08`, **superseded: true**. The older half of the version pair;
   all its chunks are marked superseded so the retriever filters them out by default. Contains
   some image-only pages.
2. **Academic Rules Handbook (Jun 2026)** — `academic-rules-handbook-jun-2026.pdf`, 58 pages,
   `2026-06`, current. The current half of the version pair, with numbered clauses (e.g.
   attendance is clause 1.21). Contains some image-only pages.
3. **Prospectus 2026 – Academic Rules and Regulations** —
   `prospectus-2026-academic-rules-and-regulations.pdf`, 5 pages, `2026`, current. The same
   rules in condensed form with **different clause numbers** (attendance is clause 1 here, 1.21
   in the handbook) — a version-sensitive and exact-term case.
4. **Student Handbook (Jun 2026)** — `student-handbook-jun-2026.pdf`, 64 pages, `2026-06`.
   Long definitions, including a multi-section Generative AI policy a fixed-size chunker would
   split mid-clause.
5. **Annual Report 2019-20** — `annual-report-2019-20.pdf`, 33 pages, `2019-20`. Tables of
   faculty, graduates and publications; part of a versions-over-time set with (6).
6. **Annual Report 2023-24** — `annual-report-2023-24.pdf`, 85 pages, `2023-24`. Same report,
   later edition — tables and change over time.
7. **Fee Structure page** — `fee-structure-page.html`, `2026-27`. HTML tables: tuition per
   credit hour, miscellaneous fees — exact amounts.
8. **Grading page** — `grading-page.html`, `2026`. HTML tables: grade points and thresholds.
9. **Faculty Entrepreneurship and Technical Start-ups Policy** —
   `faculty-entrepreneurship-and-technical-start-ups-policy.pdf`, 8 pages, `2022-05`.
   **Fully image-only — no text layer on any page** (confirmed: `extract_text()` empty for all
   8 pages). This is the OCR document.

## The seven required properties, mapped

1. **≥6 documents and ≥40 pages** — 9 documents, 279 PDF pages + 2 HTML. ✓
2. **Two versions of one policy** — Undergraduate Academic Rules 2023 (superseded) vs the 2026
   Academic Rules Handbook and the 2026 Prospectus. The retriever's `superseded` filter is what
   stops it from confidently quoting the repealed 2023 clauses. ✓
3. **Scanned, image-only PDF** — the Faculty Entrepreneurship policy (8 pages, no text layer),
   which forces the OCR path in `extract.py`. ✓
4. **Table with real information** — Fee Structure and Grading HTML pages, plus the two Annual
   Reports. ✓
5. **Long definitions a fixed chunker would cut** — the 64-page Student Handbook. ✓
6. **Deliberately absent topic** — student housing / hostel and dormitory policy is excluded on
   purpose. Questions like "How do I apply for a hostel room?" must return
   `answered_from_context: false`; this drives the must-abstain evaluation. ✓
7. **Exact-term content** — fee per credit hour (Fee Structure), CGPA thresholds (Academic
   Rules), and clause numbers that differ between the handbook and the prospectus. ✓

## What could not be recovered (honest)

- **OCR was not run on the development machine** for this session: `tesseract` and `poppler`
  are not installed, so the 8 image-only pages of the Faculty Entrepreneurship policy — and
  the scattered image-only pages found in the 2026 handbook, the student handbook and the 2023
  rules — were not text-extracted locally. The indexer image installs `tesseract-ocr` and
  `poppler-utils` (`indexer/Dockerfile`), so OCR runs on the cluster. This is the honest
  "document the loss" path the assignment allows.
- **Mixed-scan finding**: the scanned policy is not the only OCR case. Three of the longer
  "text" PDFs also contain image-only pages, which means OCR coverage matters more than a
  single-document view would suggest. Recorded in `docs/PIPELINE.md` and
  `docs/FAILURE-ANALYSIS.md`.
