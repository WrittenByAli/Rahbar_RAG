"""Stage 1: Extract. PDF (or HTML, or Markdown) to text, page by page."""

from __future__ import annotations

from html.parser import HTMLParser
from pathlib import Path

from .models import Document, Page

_SKIP_TAGS = {"script", "style", "noscript", "template", "svg", "head"}
_BLOCK_TAGS = {
    "p", "div", "section", "article", "header", "footer", "nav", "li", "tr",
    "table", "ul", "ol", "br", "hr",
}
_HEADING_TAGS = {"h1", "h2", "h3", "h4", "h5", "h6"}


class _HTMLTextExtractor(HTMLParser):
    """Strips tags/scripts/styles/comments; real <h1>-<h6> become `## text`
    lines so the existing Markdown-style heading detector in chunk.py picks
    them up, instead of random bits of markup or CSS being mistaken for one."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._parts: list[str] = []
        self._skip_depth = 0
        self._heading_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in _SKIP_TAGS:
            self._skip_depth += 1
        elif tag in _HEADING_TAGS:
            self._heading_depth += 1
            self._parts.append("\n## ")
        elif tag in _BLOCK_TAGS:
            self._parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in _SKIP_TAGS and self._skip_depth > 0:
            self._skip_depth -= 1
        elif tag in _HEADING_TAGS and self._heading_depth > 0:
            self._heading_depth -= 1
            self._parts.append("\n")
        elif tag in _BLOCK_TAGS:
            self._parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self._skip_depth == 0 and data.strip():
            self._parts.append(data)

    def text(self) -> str:
        return "".join(self._parts)


def _html_to_text(raw_html: str) -> str:
    parser = _HTMLTextExtractor()
    parser.feed(raw_html)
    parser.close()
    import re

    text = parser.text()
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def extract(path: str, doc_version: str, superseded: bool) -> Document:
    """Return the document's text page by page.

    Detect pages with no text layer and OCR them; mark those pages ocr=True.
    """
    p = Path(path)
    suffix = p.suffix.lower()
    source = p.name

    if suffix == ".pdf":
        pages = _extract_pdf(p, source)
    elif suffix == ".html":
        raw = p.read_text(encoding="utf-8", errors="replace")
        pages = [Page(source=source, page=1, text=_html_to_text(raw), ocr=False)]
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
