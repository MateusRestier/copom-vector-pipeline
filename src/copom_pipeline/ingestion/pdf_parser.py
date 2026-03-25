"""PDF text extraction for COPOM documents.

COPOM PDFs are born-digital (not scanned), so pdfplumber gives clean
text extraction without OCR.  The parser joins pages with a single
newline and returns a ParsedDocument dataclass.
"""

from __future__ import annotations

import io
import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class ParsedDocument:
    """Text extracted from a single PDF file."""
    text: str
    page_count: int


class PdfParser:
    """Extracts plain text from PDF bytes using pdfplumber."""

    def parse(self, raw_bytes: bytes) -> ParsedDocument | None:
        """Parse PDF bytes and return extracted text.

        Returns None if the PDF cannot be parsed or yields no text.
        """
        try:
            import pdfplumber  # type: ignore
        except ImportError:
            raise ImportError(
                "pdfplumber is required for PDF parsing. "
                "Install it with: pip install pdfplumber"
            )

        try:
            with pdfplumber.open(io.BytesIO(raw_bytes)) as pdf:
                page_count = len(pdf.pages)
                pages_text = []
                for page in pdf.pages:
                    text = page.extract_text()
                    if text:
                        pages_text.append(text)

            full_text = "\n".join(pages_text).strip()
            if not full_text:
                logger.warning("PDF yielded no text (%d pages).", page_count)
                return None

            return ParsedDocument(text=full_text, page_count=page_count)

        except Exception as exc:
            logger.error("Failed to parse PDF: %s", exc)
            return None
