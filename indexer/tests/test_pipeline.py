"""Tests for the indexer pipeline stages."""

from __future__ import annotations

from pathlib import Path

from pipeline.chunk import chunk
from pipeline.clean import clean
from pipeline.extract import extract
from pipeline.models import Document, Page


def test_extract_markdown_file() -> None:
    """Extract should handle .md files as single-page documents."""
    fixtures = Path(__file__).resolve().parents[2] / "eval" / "fixtures"
    md_files = list(fixtures.glob("*.md"))
    assert md_files, "No fixture markdown files found"
    doc = extract(str(md_files[0]), "test", False)
    assert isinstance(doc, Document)
    assert len(doc.pages) >= 1
    assert doc.pages[0].text.strip() != ""


def test_clean_preserves_headings() -> None:
    """Clean must not strip section headings."""
    doc = Document(
        source="test.md", doc_version="1.0", superseded=False,
        pages=[Page(source="test.md", page=1,
                    text="## Important Section\n\nSome content here.\n\nMore content.")]
    )
    cleaned = clean(doc)
    assert "Important Section" in cleaned.pages[0].text


def test_chunk_respects_size_limit() -> None:
    """Every chunk must be under the size limit."""
    text = ("## Section One\n\n" + " ".join(["word"] * 200)
            + "\n\n## Section Two\n\n" + " ".join(["word"] * 200))
    doc = Document(
        source="test.md", doc_version="1.0", superseded=False,
        pages=[Page(source="test.md", page=1, text=text)]
    )
    chunks = chunk(doc, size=100, overlap=10)
    assert len(chunks) >= 2
    for c in chunks:
        word_count = len(c.text.split())
        assert word_count <= 120


def test_chunk_ids_are_stable() -> None:
    """Same input must produce the same chunk IDs."""
    doc = Document(
        source="test.md", doc_version="1.0", superseded=False,
        pages=[Page(source="test.md", page=1, text="## Heading\n\nSome text content.")]
    )
    chunks1 = chunk(doc, size=400, overlap=50)
    chunks2 = chunk(doc, size=400, overlap=50)
    assert [c.id for c in chunks1] == [c.id for c in chunks2]


def test_chunk_carries_metadata() -> None:
    """Every chunk must carry source, section, page, doc_version, superseded."""
    doc = Document(
        source="policy.pdf", doc_version="2026", superseded=False,
        pages=[Page(source="policy.pdf", page=3,
                    text="## Rules\n\nStudents must attend classes regularly.")]
    )
    chunks = chunk(doc, size=400, overlap=50)
    assert len(chunks) >= 1
    for c in chunks:
        assert c.source == "policy.pdf"
        assert c.doc_version == "2026"
        assert c.superseded is False
        meta = c.metadata()
        assert set(meta.keys()) == {"source", "section", "page", "doc_version", "superseded"}
