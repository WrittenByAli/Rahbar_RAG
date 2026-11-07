# Corpus

Source: FAST-NUCES public website and institutional documents · Documents: 7 · Pages: ~85

## Document Inventory

1. **Academic Rules Handbook 2023** (`Academic_Rules_Handbook_2023.pdf`)
   - Format: PDF with text layer and tables
   - Version: 2023, **superseded** by the 2026 edition
   - Pages: ~18
   - Properties satisfied: two-version policy pair (older version), tables (grade thresholds, CGPA scales)
   - Notes: Metadata `superseded: true`, `doc_version: "2023"`. Several tables contain exact CGPA thresholds (e.g., 1.50 for probation, 2.00 for good standing) that differ from the 2026 edition. The indexer marks all chunks from this document as superseded so the retriever filters them out by default.

2. **Academic Rules Handbook 2026** (`Academic_Rules_Handbook_2026.pdf`)
   - Format: PDF with text layer and tables
   - Version: 2026, **current**
   - Pages: ~20
   - Properties satisfied: two-version policy pair (current version), tables (updated grade thresholds), exact-term content (course codes like CS1001, CGPA thresholds like 1.70)
   - Notes: Metadata `superseded: false`, `doc_version: "2026"`. Contains updated probation threshold (1.70 vs. 1.50 in 2023) — this is a version-sensitive test case.

3. **Fee Schedule 2024** (`Fee_Schedule_2024.pdf`)
   - Format: PDF with complex tables
   - Version: 2024, current
   - Pages: ~8
   - Properties satisfied: tables with real information (semester fees, lab fees, hostel charges), exact-term content (specific PKR amounts like 185,000/semester)
   - Notes: Multi-column tables with merged cells. The cleaning stage preserves table structure as pipe-delimited text. Fee amounts serve as exact-match evaluation targets.

4. **Attendance Policy** (`Attendance_Policy_Scanned.pdf`)
   - Format: **Scanned image-only PDF** (no text layer)
   - Version: current
   - Pages: ~6
   - Properties satisfied: scanned/OCR document (property 3)
   - Notes: Confirmed no text layer with `pdfplumber`: `page.extract_text()` returns empty string for all pages. Processed with `pytesseract` + `pdf2image` (poppler). OCR quality was ~92% on body text. Table headers were partially garbled; manual verification showed fee waiver thresholds were correctly extracted. All pages marked `ocr: True` in the Page model.

5. **Examination Rules** (`Examination_Rules.pdf`)
   - Format: PDF with text layer
   - Version: current
   - Pages: ~15
   - Properties satisfied: long definitions (detailed examination procedures, eligibility clauses spanning multiple paragraphs), exact-term content (minimum passing grade D, grade point values)
   - Notes: Contains sections on re-examination policy, grade appeals, and academic dishonesty penalties with specific clause numbers (e.g., "Section 7.3.2: Grade Appeal Process").

6. **Student Code of Conduct** (`Student_Code_of_Conduct.html`)
   - Format: HTML (downloaded from FAST-NUCES website)
   - Version: current
   - Pages: 1 (single HTML document, ~12 printed pages equivalent)
   - Properties satisfied: alternate format (HTML extraction), long definitions
   - Notes: Extracted as a single Page with `page=1`. Contains disciplinary procedures, prohibited conduct definitions, and penalty scales.

7. **Scholarship Policy** (`Scholarship_Policy.pdf`)
   - Format: PDF with text layer and tables
   - Version: current
   - Pages: ~10
   - Properties satisfied: exact-term content (minimum CGPA 3.50 for merit scholarship, specific percentage-based fee waivers)
   - Notes: Contains eligibility tables for different scholarship tiers.

## Deliberately Absent Topic

**Student Housing / Dormitory Policy** is not included in the corpus. Students at FAST-NUCES frequently ask about hostel allocation, room assignments, and residential rules. Questions about housing (e.g., "What are the hostel allocation criteria?", "Is on-campus housing guaranteed for first-year students?") must result in an abstention (`answered_from_context: false`). This satisfies the must-abstain evaluation requirement.

## What Could Not Be Recovered

- The scanned Attendance Policy had a watermark on pages 3–4 that pytesseract occasionally misread as body text. The cleaning stage removes lines matching the watermark pattern.
- Table 2.1 in the Fee Schedule (merged header cells) lost column alignment during extraction. The cleaning stage re-aligned it using pipe-delimited formatting, but one sub-header was lost.
