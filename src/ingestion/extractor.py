"""Text extraction from documents: DOCX, PDF, Markdown, plain text."""

from io import BytesIO
from pathlib import Path

from src.logging_config import get_logger

logger = get_logger(__name__)


class DocumentExtractor:
    """Extracts raw text from various document formats."""

    SUPPORTED_EXTENSIONS = {".pdf", ".docx", ".md", ".txt"}

    @classmethod
    def supports(cls, file_path: str | Path) -> bool:
        """Check if this extractor supports the given file type."""
        ext = Path(file_path).suffix.lower()
        return ext in cls.SUPPORTED_EXTENSIONS

    def extract(self, content: bytes, file_type: str) -> str:
        """Extract raw text from document bytes.

        Args:
            content: Raw file bytes.
            file_type: File extension (".pdf", ".docx", ".md", ".txt").

        Returns:
            Extracted plain text.
        """
        file_type = file_type.lower()
        if not file_type.startswith("."):
            file_type = "." + file_type

        if file_type == ".docx":
            return self._extract_docx(content)
        elif file_type == ".pdf":
            return self._extract_pdf(content)
        elif file_type in (".md", ".txt"):
            return self._extract_text(content)
        else:
            raise ValueError(f"Unsupported file type: {file_type}")

    def _extract_docx(self, content: bytes) -> str:
        """Extract text from a .docx file."""
        import docx

        try:
            doc = docx.Document(BytesIO(content))
            paragraphs = [p.text for p in doc.paragraphs if p.text.strip()]
            return "\n\n".join(paragraphs)
        except Exception as e:
            logger.error("docx_extraction_failed", error=str(e))
            raise

    def _extract_pdf(self, content: bytes) -> str:
        """Extract text from a .pdf file."""
        import fitz  # PyMuPDF

        try:
            doc = fitz.open(stream=content, filetype="pdf")
            pages = []
            for page in doc:
                text = page.get_text()
                if text.strip():
                    pages.append(text.strip())
            doc.close()
            return "\n\n".join(pages)
        except Exception as e:
            logger.error("pdf_extraction_failed", error=str(e))
            raise

    def _extract_text(self, content: bytes) -> str:
        """Extract text from plain text or markdown files."""
        try:
            return content.decode("utf-8")
        except UnicodeDecodeError:
            return content.decode("latin-1", errors="replace")
