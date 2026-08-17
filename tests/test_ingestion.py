"""Tests for the ingestion pipeline — extraction, metadata, chunking, and embedding."""

import pytest
from io import BytesIO

from src.ingestion.extractor import DocumentExtractor
from src.ingestion.metadata import MetadataExtractor
from src.ingestion.chunker import DocumentChunker


# ──────────────────────────────────────────────
# DocumentExtractor tests
# ──────────────────────────────────────────────


class TestDocumentExtractor:
    def test_extract_txt(self):
        extractor = DocumentExtractor()
        text = extractor.extract(b"Hello, world!", ".txt")
        assert text == "Hello, world!"

    def test_extract_md(self):
        extractor = DocumentExtractor()
        text = extractor.extract(b"# Title\n\nContent.", ".md")
        assert "# Title" in text
        assert "Content" in text

    def test_extract_unsupported_raises(self):
        extractor = DocumentExtractor()
        with pytest.raises(ValueError, match="Unsupported file type"):
            extractor.extract(b"data", ".xyz")

    def test_supports_method(self):
        assert DocumentExtractor.supports("file.pdf") is True
        assert DocumentExtractor.supports("file.docx") is True
        assert DocumentExtractor.supports("file.epub") is True
        assert DocumentExtractor.supports("file.md") is True
        assert DocumentExtractor.supports("file.txt") is True
        assert DocumentExtractor.supports("file.xlsx") is False

    def test_extract_epub(self):
        """EPUB text extraction follows the OPF spine order (stdlib only)."""
        import zipfile

        buf = BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            z.writestr("mimetype", "application/epub+zip")
            z.writestr(
                "OEBPS/content.opf",
                """<?xml version="1.0" encoding="utf-8"?>
<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="id">
  <manifest>
    <item id="ch1" href="Text/chapter1.xhtml" media-type="application/xhtml+xml"/>
    <item id="ch2" href="Text/chapter2.xhtml" media-type="application/xhtml+xml"/>
  </manifest>
  <spine toc="ncx">
    <itemref idref="ch1"/>
    <itemref idref="ch2"/>
  </spine>
</package>""",
            )
            z.writestr(
                "OEBPS/Text/chapter1.xhtml",
                "<html xmlns='http://www.w3.org/1999/xhtml'><body>"
                "<p>Chapter one begins with <em>emphasis</em>.</p></body></html>",
            )
            z.writestr(
                "OEBPS/Text/chapter2.xhtml",
                "<html xmlns='http://www.w3.org/1999/xhtml'><body>"
                "<p>Chapter two continues the story.</p></body></html>",
            )

        extractor = DocumentExtractor()
        text = extractor.extract(buf.getvalue(), ".epub")
        assert "Chapter one begins with" in text
        assert "Chapter two continues" in text
        # Spine order preserved: chapter one appears before chapter two.
        assert text.index("one begins") < text.index("two continues")

    def test_extract_epub_invalid_zip_raises(self):
        extractor = DocumentExtractor()
        with pytest.raises(ValueError, match="Invalid EPUB"):
            extractor.extract(b"not a zip at all", ".epub")


# ──────────────────────────────────────────────
# MetadataExtractor tests
# ──────────────────────────────────────────────


class TestMetadataExtractor:
    def test_extract_requirements(self):
        extractor = MetadataExtractor()
        text = "This implements REQ-101 and REQ-205 for authentication."
        metadata = extractor.extract(text)
        assert "REQ-101" in metadata["requirement_ids"]
        assert "REQ-205" in metadata["requirement_ids"]

    def test_extract_change_requests(self):
        extractor = MetadataExtractor()
        text = "See CR-0891 and CR-1234 for details."
        metadata = extractor.extract(text)
        assert "CR-0891" in metadata["change_request_ids"]
        assert "CR-1234" in metadata["change_request_ids"]

    def test_extract_project_names(self):
        extractor = MetadataExtractor()
        text = "Project: Payment Gateway Migration\nThis project aims to..."
        metadata = extractor.extract(text)
        assert any("Payment Gateway Migration" in p for p in metadata["project_names"])

    def test_extract_dates(self):
        extractor = MetadataExtractor()
        text = "Implemented on 2024-01-15. Reviewed 03/15/2024."
        metadata = extractor.extract(text)
        assert "2024-01-15" in metadata["dates"]

    def test_extract_repositories(self):
        extractor = MetadataExtractor()
        text = "Code at https://github.com/org/repo and https://dev.azure.com/org/project/_git/repo"
        metadata = extractor.extract(text)
        assert any("github.com" in r for r in metadata["repositories"])

    def test_extract_versions(self):
        extractor = MetadataExtractor()
        text = "Version 2.1.0 includes major updates."
        metadata = extractor.extract(text)
        assert "2.1.0" in metadata["versions"]

    def test_empty_text(self):
        extractor = MetadataExtractor()
        metadata = extractor.extract("")
        assert metadata["requirement_ids"] == []
        assert metadata["project_names"] == []
        assert metadata["dates"] == []


# ──────────────────────────────────────────────
# DocumentChunker tests
# ──────────────────────────────────────────────


class TestDocumentChunker:
    def test_chunk_small_text(self):
        chunker = DocumentChunker(chunk_size=1000, chunk_overlap=200)
        text = "This is a short text."
        chunks = chunker.chunk(text)
        assert len(chunks) == 1
        assert chunks[0].content == text
        assert chunks[0].chunk_index == 0
        assert chunks[0].token_count > 0

    def test_chunk_large_text(self):
        chunker = DocumentChunker(chunk_size=100, chunk_overlap=20)
        # Generate text with sentences to test natural break points
        text = ". ".join([f"This is sentence number {i}" for i in range(50)]) + "."
        chunks = chunker.chunk(text)
        assert len(chunks) > 1
        # Each chunk should be <= chunk_size + some buffer for sentence completeness
        for chunk in chunks:
            assert len(chunk.content) <= 100 + 50  # generous buffer

    def test_overlap(self):
        chunker = DocumentChunker(chunk_size=100, chunk_overlap=20)
        text = "AAAAAAAAAA " * 50  # No natural breaks, so chunks will use overlap
        chunks = chunker.chunk(text)
        assert len(chunks) > 1
        # Check that chunk positions advance properly with overlap
        for i in range(1, len(chunks)):
            assert chunks[i].chunk_index == i
            # End of previous chunk should be after start of next (overlap)
            assert chunks[i - 1].end_char > chunks[i].start_char

    def test_empty_text(self):
        chunker = DocumentChunker()
        chunks = chunker.chunk("")
        assert chunks == []

    def test_chunk_indices_sequential(self):
        chunker = DocumentChunker(chunk_size=50, chunk_overlap=10)
        text = "A " * 100
        chunks = chunker.chunk(text)
        for i, chunk in enumerate(chunks):
            assert chunk.chunk_index == i
