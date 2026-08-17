"""Text extraction from documents: DOCX, PDF, EPUB, Markdown, plain text."""

from io import BytesIO
from pathlib import Path

from src.logging_config import get_logger

logger = get_logger(__name__)


class DocumentExtractor:
    """Extracts raw text from various document formats."""

    SUPPORTED_EXTENSIONS = {".pdf", ".docx", ".epub", ".md", ".txt"}

    @classmethod
    def supports(cls, file_path: str | Path) -> bool:
        """Check if this extractor supports the given file type."""
        ext = Path(file_path).suffix.lower()
        return ext in cls.SUPPORTED_EXTENSIONS

    def extract(self, content: bytes, file_type: str) -> str:
        """Extract raw text from document bytes.

        Args:
            content: Raw file bytes.
            file_type: File extension (".pdf", ".docx", ".epub", ".md", ".txt").

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
        elif file_type == ".epub":
            return self._extract_epub(content)
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

    def _extract_epub(self, content: bytes) -> str:
        """Extract text from an EPUB file (a ZIP of XHTML chapters).

        Standard-library only (zipfile + ElementTree). Reads chapters in the
        order declared by the OPF spine; falls back to sorted archive names
        when no OPF can be parsed. DRM-protected or malformed ebooks yield
        whatever text is recoverable (possibly empty).
        """
        import zipfile

        try:
            zf = zipfile.ZipFile(BytesIO(content))
        except zipfile.BadZipFile as e:
            raise ValueError(f"Invalid EPUB (not a ZIP archive): {e}")

        try:
            names = zf.namelist()
            chapter_files: list[str] = []
            opf_name = next((n for n in names if n.lower().endswith(".opf")), None)
            if opf_name:
                try:
                    chapter_files = self._epub_reading_order(zf.read(opf_name), opf_name)
                except Exception as e:  # noqa: BLE001
                    logger.warning("epub_opf_parse_failed", error=str(e))
            if not chapter_files:
                chapter_files = sorted(
                    n for n in names if n.lower().endswith((".xhtml", ".html", ".htm"))
                )

            sections: list[str] = []
            for path in chapter_files:
                if path not in names:
                    continue
                try:
                    text = self._html_to_text(zf.read(path))
                except Exception as e:  # noqa: BLE001
                    logger.warning("epub_chapter_failed", path=path, error=str(e))
                    continue
                if text.strip():
                    sections.append(text.strip())
            return "\n\n".join(sections)
        finally:
            zf.close()

    @staticmethod
    def _epub_reading_order(opf_xml: bytes, opf_name: str) -> list[str]:
        """Return manifest item hrefs in spine order, resolved relative to the OPF."""
        import re
        from urllib.parse import unquote, urljoin
        from xml.etree import ElementTree as ET

        try:
            root = ET.fromstring(opf_xml)
        except ET.ParseError:
            return []

        def tag(name: str) -> str:
            return re.sub(r"\{.*?\}", "", name)

        manifest: dict[str, str] = {}
        for item in root.iter():
            if tag(item.tag) == "item" and item.get("id") and item.get("href"):
                manifest[item.get("id")] = item.get("href")

        opf_dir = opf_name.rsplit("/", 1)[0] + "/"
        hrefs: list[str] = []
        for ref in root.iter():
            if tag(ref.tag) != "itemref" or not ref.get("idref"):
                continue
            href = manifest.get(ref.get("idref"))
            if not href:
                continue
            resolved = urljoin(opf_dir, unquote(href)).lstrip("/")
            if resolved not in hrefs:
                hrefs.append(resolved)
        return hrefs

    @staticmethod
    def _html_to_text(data: bytes) -> str:
        """Strip HTML/SGML markup from an XHTML chapter (stdlib only)."""
        import html as html_mod
        import re
        from xml.etree import ElementTree as ET

        text = data.decode("utf-8", errors="replace")
        try:
            root = ET.fromstring(text)
            return "\n".join(t for t in root.itertext() if t and t.strip())
        except ET.ParseError:
            # Not well-formed XML — strip scripts/styles and tags as a fallback.
            cleaner = re.compile(r"<script.*?</script>", re.S | re.I).sub(" ", text)
            cleaner = re.compile(r"<style.*?</style>", re.S | re.I).sub(" ", cleaner)
            cleaner = re.compile(r"<[^>]+>", re.S).sub(" ", cleaner)
            return html_mod.unescape(cleaner)

    def _extract_text(self, content: bytes) -> str:
        """Extract text from plain text or markdown files."""
        try:
            return content.decode("utf-8")
        except UnicodeDecodeError:
            return content.decode("latin-1", errors="replace")
