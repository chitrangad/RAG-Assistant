"""Document chunking for embedding and retrieval."""

import re
from dataclasses import dataclass


@dataclass
class TextChunk:
    """A chunk of text with positional metadata."""

    chunk_index: int
    content: str
    token_count: int
    start_char: int
    end_char: int


class DocumentChunker:
    """Splits documents into overlapping chunks for embedding.

    Settings from spec:
        chunk_size: 1000 characters
        chunk_overlap: 200 characters
    """

    def __init__(self, chunk_size: int = 1000, chunk_overlap: int = 200):
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap

    def chunk(self, text: str) -> list[TextChunk]:
        """Split text into overlapping chunks.

        Uses sentence-aware splitting: tries to break at sentence boundaries
        (period, newline) near the chunk boundary.
        """
        if not text.strip():
            return []

        chunks: list[TextChunk] = []
        start = 0
        text_len = len(text)
        chunk_index = 0

        while start < text_len:
            end = min(start + self.chunk_size, text_len)

            # Try to break at a natural boundary if we're not at the end
            if end < text_len:
                # Look for a sentence break within the last 200 chars of the chunk
                search_start = max(start, end - 200)
                break_pos = self._find_break_point(text, search_start, end)

                if break_pos is not None:
                    end = break_pos + 1

            chunk_text = text[start:end].strip()
            token_count = self._estimate_tokens(chunk_text)

            if chunk_text:
                chunks.append(
                    TextChunk(
                        chunk_index=chunk_index,
                        content=chunk_text,
                        token_count=token_count,
                        start_char=start,
                        end_char=end,
                    )
                )
                chunk_index += 1

            # Advance with overlap, ensuring forward progress
            # (If overlap would push start backward or stall, skip overlap)
            new_start = end - self.chunk_overlap
            if new_start <= start:
                start = end
            else:
                start = new_start

            if start >= text_len or end >= text_len:
                break

        return chunks

    def _find_break_point(self, text: str, search_start: int, search_end: int) -> int | None:
        """Find a natural sentence/paragraph break point.

        Prefers: period+space+capital, then double newline, then single newline.
        """
        segment = text[search_start:search_end]

        # Try period followed by space and capital letter (sentence boundary)
        for match in re.finditer(r"\.\s+(?=[A-Z])", segment):
            pos = search_start + match.end() - 1
            return pos

        # Try double newline (paragraph boundary)
        for match in re.finditer(r"\n\n", segment):
            pos = search_start + match.end() - 1
            return pos

        # Try single newline
        for match in re.finditer(r"\n", segment):
            pos = search_start + match.end() - 1
            return pos

        return None

    @staticmethod
    def _estimate_tokens(text: str) -> int:
        """Rough token estimation: ~4 chars per token."""
        return max(1, len(text) // 4)
