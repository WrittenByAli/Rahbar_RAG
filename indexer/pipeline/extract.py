"""Stage 1: Extract. PDF (or HTML, or Markdown) to text, page by page."""

from __future__ import annotations

from pathlib import Path

from .models import Document, Page


def extract(path: str, doc_version: str, superseded: bool) -> Document:
    """Return the document's text page by page.

    Detect pages with no text layer and OCR them; mark those pages ocr=True.
    """
    p = Path(path)
    suffix = p.suffix.lower()
    source = p.name

    if suffix == ".pdf":
        pages = _extract_pdf(p, source)
    elif suffix in (".md", ".txt", ".html"):
        text = p.read_text(encoding="utf-8", errors="replace")
        pages = [Page(source=source, page=1, text=text, ocr=False)]
    else:
        text = p.read_text(encoding="utf-8", errors="replace")
        pages = [Page(source=source, page=1, text=text, ocr=False)]

    return Document(source=source, doc_version=doc_version, superseded=superseded, pages=pages)


def _extract_pdf(p: Path, source: str) -> list[Page]:
    import pdfplumber

    pages: list[Page] = []
    with pdfplumber.open(str(p)) as pdf:
        for i, pdf_page in enumerate(pdf.pages, start=1):
            text = pdf_page.extract_text() or ""
            if text.strip():
                pages.append(Page(source=source, page=i, text=text, ocr=False))
            else:
                ocr_text = _ocr_page(str(p), i)
                pages.append(Page(source=source, page=i, text=ocr_text, ocr=True))
    return pages


def _ocr_page(pdf_path: str, page_number: int) -> str:
    from pdf2image import convert_from_path
    from pytesseract import image_to_string

    images = convert_from_path(pdf_path, first_page=page_number, last_page=page_number)
    if not images:
        return ""
    return image_to_string(images[0]) or ""
