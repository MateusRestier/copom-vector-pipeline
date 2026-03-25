"""Text cleaning for COPOM PDF content.

COPOM documents are formal legal/monetary policy text, so this module
uses regex-based cleaning only (no spaCy lemmatization needed).

Operations performed:
  1. Decode soft hyphens and ligatures (common pdfplumber artifacts).
  2. Remove repeated page headers/footers that appear in COPOM PDFs.
  3. Normalize whitespace (multiple spaces, tabs → single space).
  4. Normalize line endings.
  5. Strip leading/trailing whitespace.
"""

from __future__ import annotations

import re
import unicodedata


# Soft hyphen (U+00AD) and zero-width characters inserted by pdfplumber
_SOFT_HYPHEN = "\u00ad"
_ZERO_WIDTH = re.compile(r"[\u200b\u200c\u200d\ufeff]")

# Common COPOM PDF header/footer patterns (case-insensitive)
_HEADER_FOOTER_PATTERNS = [
    re.compile(r"Banco Central do Brasil\s*\n", re.IGNORECASE),
    re.compile(r"Copom\s*[-–]\s*\d+[ªa]?\s*Reunião\s*\n", re.IGNORECASE),
    re.compile(r"Ata da?\s+\d+[ªa]?\s+Reunião do Copom\s*\n", re.IGNORECASE),
    re.compile(r"\bwww\.bcb\.gov\.br\b\s*\n", re.IGNORECASE),
    re.compile(r"Página \d+ de \d+\s*\n", re.IGNORECASE),
    re.compile(r"^\s*\d+\s*$", re.MULTILINE),  # lone page numbers
]

# Ligatures that pdfplumber may not normalise
_LIGATURE_MAP = str.maketrans({
    "\ufb00": "ff",
    "\ufb01": "fi",
    "\ufb02": "fl",
    "\ufb03": "ffi",
    "\ufb04": "ffl",
    "\ufb05": "st",
    "\ufb06": "st",
})

_MULTIPLE_SPACES = re.compile(r"[ \t]+")
_MULTIPLE_NEWLINES = re.compile(r"\n{3,}")


def clean_text(text: str) -> str:
    """Clean raw PDF text for embedding.

    Args:
        text: Raw text as extracted by pdfplumber.

    Returns:
        Cleaned text suitable for chunking and embedding.
    """
    if not text:
        return text

    # 1. Remove soft hyphens and zero-width characters
    text = text.replace(_SOFT_HYPHEN, "")
    text = _ZERO_WIDTH.sub("", text)

    # 2. Resolve ligatures
    text = text.translate(_LIGATURE_MAP)

    # 3. Unicode NFKC normalization (normalises accented chars, fractions, etc.)
    text = unicodedata.normalize("NFKC", text)

    # 4. Remove repeated page headers/footers
    for pattern in _HEADER_FOOTER_PATTERNS:
        text = pattern.sub("", text)

    # 5. Re-join words split across lines with a hyphen
    text = re.sub(r"-\n(\S)", r"\1", text)

    # 6. Normalize whitespace
    text = _MULTIPLE_SPACES.sub(" ", text)
    text = _MULTIPLE_NEWLINES.sub("\n\n", text)

    return text.strip()
