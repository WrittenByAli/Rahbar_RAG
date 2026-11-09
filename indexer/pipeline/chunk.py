"""Stage 3: Chunk. Structure-aware, with overlap."""

from __future__ import annotations

import hashlib
import re

from .models import Chunk, Document


def chunk(doc: Document, size: int, overlap: int) -> list[Chunk]:
    """Split on sections, then paragraphs, then sentences, keeping each chunk under
    `size` tokens, with `overlap` tokens shared between neighbours. Every chunk keeps
    the section heading it sits under, its page, doc_version and superseded."""
    sections = _split_into_sections(doc)
    raw_chunks: list[dict] = []

    for section_heading, section_text, page_num in sections:
        paragraphs = re.split(r"\n{2,}", section_text)
        buffer_words: list[str] = []

        for para in paragraphs:
            words = para.split()
            if not words:
                continue
            if len(buffer_words) + len(words) <= size:
                buffer_words.extend(words)
            else:
                if buffer_words:
                    raw_chunks.append({
                        "text": " ".join(buffer_words),
                        "section": section_heading,
                        "page": page_num,
                    })
                if len(words) <= size:
                    buffer_words = list(words)
                else:
                    for sent_chunk in _split_sentences(words, size):
                        raw_chunks.append({
                            "text": " ".join(sent_chunk),
                            "section": section_heading,
                            "page": page_num,
                        })
                    buffer_words = []
        if buffer_words:
            raw_chunks.append({
                "text": " ".join(buffer_words),
                "section": section_heading,
                "page": page_num,
            })

    chunks = _apply_overlap(raw_chunks, overlap, doc)
    return chunks


def _split_into_sections(doc: Document) -> list[tuple[str, str, int]]:
    """Return (heading, text, page_number) for each section."""
    sections: list[tuple[str, str, int]] = []
    current_heading = "Introduction"
    current_text: list[str] = []
    current_page = 1

    for page in doc.pages:
        for line in page.text.splitlines():
            heading = _extract_heading(line)
            if heading:
                if current_text:
                    sections.append((current_heading, "\n".join(current_text), current_page))
                    current_text = []
                current_heading = heading
                current_page = page.page
            else:
                current_text.append(line)
                if not sections:
                    current_page = page.page

    if current_text:
        sections.append((current_heading, "\n".join(current_text), current_page))

    if not sections:
        full_text = "\n".join(p.text for p in doc.pages)
        sections = [(current_heading, full_text, 1)]

    return sections


_NUMBERED_CLAUSE = re.compile(r"^(\d+(?:\.\d+)*)\s+([A-Z][A-Za-z].{2,78})$")


def _looks_like_table_row(stripped: str) -> bool:
    """Reject ALL-CAPS lines that are table rows or datelines, not real
    headings: checkbox columns ("X X X X"), single-letter column codes
    ("A B C"), or lines that are mostly digits/punctuation."""
    tokens = stripped.split()
    single_char_tokens = sum(1 for t in tokens if len(t) == 1 and t.isalpha())
    if single_char_tokens >= 2:
        return True
    digit_chars = sum(1 for ch in stripped if ch.isdigit())
    if digit_chars / max(len(stripped), 1) > 0.3:
        return True
    return False


def _extract_heading(line: str) -> str | None:
    stripped = line.strip()
    if not stripped:
        return None
    match = re.match(r"^(#{1,4})\s+(.+)$", stripped)
    if match:
        return match.group(2).strip()
    # Numbered clauses, e.g. "1.21 Attendance": the real heading style FAST-NUCES
    # PDFs use, which the ALL-CAPS check below never catches.
    clause = _NUMBERED_CLAUSE.match(stripped)
    if clause and not _looks_like_table_row(stripped):
        return stripped
    if (
        len(stripped) < 80
        and stripped == stripped.upper()
        and len(stripped.split()) >= 2
        and not stripped.startswith("|")
        and re.search(r"[A-Z]", stripped)
        and not _looks_like_table_row(stripped)
    ):
        return stripped
    return None


def _split_sentences(words: list[str], size: int) -> list[list[str]]:
    chunks: list[list[str]] = []
    current: list[str] = []
    for w in words:
        current.append(w)
        if len(current) >= size:
            chunks.append(current)
            current = []
    if current:
        chunks.append(current)
    return chunks


def _apply_overlap(
    raw_chunks: list[dict], overlap: int, doc: Document
) -> list[Chunk]:
    chunks: list[Chunk] = []
    prev_words: list[str] = []

    for idx, rc in enumerate(raw_chunks):
        text = rc["text"]
        words = text.split()

        if overlap > 0 and prev_words and idx > 0:
            overlap_words = prev_words[-overlap:]
            words = overlap_words + words
            text = " ".join(words)

        chunk_id = hashlib.sha256(
            (doc.source + rc["section"] + str(idx)).encode()
        ).hexdigest()[:16]

        chunks.append(Chunk(
            id=chunk_id,
            text=text,
            source=doc.source,
            section=rc["section"],
            page=rc["page"],
            doc_version=doc.doc_version,
            superseded=doc.superseded,
        ))

        prev_words = rc["text"].split()

    return chunks
