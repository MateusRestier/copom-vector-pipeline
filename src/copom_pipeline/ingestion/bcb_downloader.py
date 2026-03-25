"""BCB (Banco Central do Brasil) COPOM document downloader.

Uses the official BCB Open Data API documented at:
  https://dadosabertos.bcb.gov.br/dataset/atas-comunicados-copom
  https://www.bcb.gov.br/conteudo/dadosabertos/BCBDeinf/elements_copom.html

API endpoints used:
  Atas list    : GET /api/servico/sitebcb/copom/atas?quantidade=N
  Ata detail   : GET /api/servico/sitebcb/copom/atas_detalhes?nro_reuniao=N
  Comunicados  : GET /api/servico/sitebcb/copom/comunicados?quantidade=N
  Comunicado   : GET /api/servico/sitebcb/copom/comunicados_detalhes?nro_reuniao=N

Document sources:
  - Atas with PDF  (meeting >= ~200): raw_bytes contains PDF content
  - Atas without PDF (meeting < 200): raw_text contains HTML of the minutes
  - Comunicados: raw_text contains HTML (no PDF available)
"""

from __future__ import annotations

import html
import logging
import os
import re
import time
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Iterator

import httpx

logger = logging.getLogger(__name__)

_BCB_BASE = "https://www.bcb.gov.br"
_ATAS_LIST      = _BCB_BASE + "/api/servico/sitebcb/copom/atas?quantidade={qty}"
_ATA_DETAIL     = _BCB_BASE + "/api/servico/sitebcb/copom/atas_detalhes?nro_reuniao={n}"
_COMUNICADOS_LIST  = _BCB_BASE + "/api/servico/sitebcb/copom/comunicados?quantidade={qty}"
_COMUNICADO_DETAIL = _BCB_BASE + "/api/servico/sitebcb/copom/comunicados_detalhes?nro_reuniao={n}"

_MAX_DOCS = 500   # max the API accepts per request


@dataclass
class RawDocument:
    """A single COPOM document as downloaded from BCB.

    Exactly one of raw_bytes or raw_text will be non-empty:
      raw_bytes — PDF bytes (atas with PDF)
      raw_text  — plain text extracted from HTML (atas without PDF, comunicados)
    """
    url: str
    title: str
    doc_type: str               # 'ata' or 'comunicado'
    meeting_date: date | None
    meeting_number: int
    raw_bytes: bytes = field(default=b"")
    raw_text: str = field(default="")

    @property
    def has_pdf(self) -> bool:
        return len(self.raw_bytes) > 0


class BcbDownloader:
    """Downloads COPOM atas and comunicados from the BCB Open Data API.

    Args:
        known_hashes:  Set of source_hash values already in the database.
        request_delay: Seconds to wait between HTTP requests.
        max_retries:   Max retry attempts per request.
    """

    def __init__(
        self,
        known_hashes: set[str] | None = None,
        request_delay: float | None = None,
        max_retries: int | None = None,
    ) -> None:
        self._known_hashes = known_hashes or set()
        self._delay = float(
            os.environ.get("BCB_REQUEST_DELAY_SECONDS", "1.0")
            if request_delay is None else request_delay
        )
        self._max_retries = int(
            os.environ.get("BCB_MAX_RETRIES", "3")
            if max_retries is None else max_retries
        )
        self._client = httpx.Client(
            timeout=30.0,
            follow_redirects=True,
            headers={"User-Agent": "copom-vector-pipeline/0.1 (research)"},
        )

    # ──────────────────────────────────────────────────────────────────
    #  Public API
    # ──────────────────────────────────────────────────────────────────

    def iter_documents(
        self,
        doc_types: list[str] = ("ata", "comunicado"),
        date_from: date | None = None,
        date_to: date | None = None,
        dry_run: bool = False,
    ) -> Iterator[RawDocument]:
        """Yield RawDocument objects for each COPOM document."""
        if "ata" in doc_types:
            yield from self._iter_atas(date_from, date_to, dry_run)
        if "comunicado" in doc_types:
            yield from self._iter_comunicados(date_from, date_to, dry_run)

    def close(self) -> None:
        self._client.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    # ──────────────────────────────────────────────────────────────────
    #  Atas
    # ──────────────────────────────────────────────────────────────────

    def _iter_atas(
        self,
        date_from: date | None,
        date_to: date | None,
        dry_run: bool,
    ) -> Iterator[RawDocument]:
        data = self._get_json(_ATAS_LIST.format(qty=_MAX_DOCS))
        items = data.get("conteudo", [])
        logger.info("Found %d atas.", len(items))

        for item in items:
            meeting_date = _parse_date(item.get("dataReferencia"))
            if not _in_date_range(meeting_date, date_from, date_to):
                continue

            meeting_number = item.get("nroReuniao") or item.get("nro_reuniao", 0)
            title = item.get("titulo", f"Ata {meeting_number}").strip()

            if dry_run:
                logger.info("[dry-run] ata #%d — %s (%s)", meeting_number, title, meeting_date)
                yield RawDocument(
                    url="", title=title, doc_type="ata",
                    meeting_date=meeting_date, meeting_number=meeting_number,
                )
                continue

            doc = self._fetch_ata_detail(meeting_number, title, meeting_date)
            if doc:
                yield doc
                time.sleep(self._delay)

    def _fetch_ata_detail(
        self, meeting_number: int, title: str, meeting_date: date | None
    ) -> RawDocument | None:
        url = _ATA_DETAIL.format(n=meeting_number)
        try:
            detail = self._get_json(url)
        except RuntimeError as exc:
            logger.error("Could not fetch ata detail #%d: %s", meeting_number, exc)
            return None

        pdf_url = detail.get("urlPdfAta", "").strip()

        # --- Ata with PDF ---
        if pdf_url:
            full_url = pdf_url if pdf_url.startswith("http") else _BCB_BASE + pdf_url
            raw = self._fetch_pdf(full_url)
            if raw:
                return RawDocument(
                    url=full_url, title=title, doc_type="ata",
                    meeting_date=meeting_date, meeting_number=meeting_number,
                    raw_bytes=raw,
                )

        # --- Ata without PDF: use textoAta HTML ---
        html_text = detail.get("textoAta", "").strip()
        if html_text:
            plain = _html_to_text(html_text)
            return RawDocument(
                url=_ATA_DETAIL.format(n=meeting_number),
                title=title, doc_type="ata",
                meeting_date=meeting_date, meeting_number=meeting_number,
                raw_text=plain,
            )

        logger.warning("Ata #%d has neither PDF nor text.", meeting_number)
        return None

    # ──────────────────────────────────────────────────────────────────
    #  Comunicados
    # ──────────────────────────────────────────────────────────────────

    def _iter_comunicados(
        self,
        date_from: date | None,
        date_to: date | None,
        dry_run: bool,
    ) -> Iterator[RawDocument]:
        data = self._get_json(_COMUNICADOS_LIST.format(qty=_MAX_DOCS))
        items = data.get("conteudo", [])
        logger.info("Found %d comunicados.", len(items))

        for item in items:
            meeting_date = _parse_date(item.get("dataReferencia"))
            if not _in_date_range(meeting_date, date_from, date_to):
                continue

            meeting_number = item.get("nro_reuniao") or item.get("nroReuniao", 0)
            title = item.get("titulo", f"Comunicado {meeting_number}").strip()

            if dry_run:
                logger.info("[dry-run] comunicado #%d — %s (%s)", meeting_number, title, meeting_date)
                yield RawDocument(
                    url="", title=title, doc_type="comunicado",
                    meeting_date=meeting_date, meeting_number=meeting_number,
                )
                continue

            doc = self._fetch_comunicado_detail(meeting_number, title, meeting_date)
            if doc:
                yield doc
                time.sleep(self._delay)

    def _fetch_comunicado_detail(
        self, meeting_number: int, title: str, meeting_date: date | None
    ) -> RawDocument | None:
        url = _COMUNICADO_DETAIL.format(n=meeting_number)
        try:
            detail = self._get_json(url)
        except RuntimeError as exc:
            logger.error("Could not fetch comunicado detail #%d: %s", meeting_number, exc)
            return None

        html_text = detail.get("textoComunicado", "").strip()
        if not html_text:
            logger.warning("Comunicado #%d has no text.", meeting_number)
            return None

        return RawDocument(
            url=url, title=title, doc_type="comunicado",
            meeting_date=meeting_date, meeting_number=meeting_number,
            raw_text=_html_to_text(html_text),
        )

    # ──────────────────────────────────────────────────────────────────
    #  HTTP helpers
    # ──────────────────────────────────────────────────────────────────

    def _fetch_pdf(self, url: str) -> bytes | None:
        for attempt in range(1, self._max_retries + 1):
            try:
                resp = self._client.get(url)
                resp.raise_for_status()
                return resp.content
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code in (403, 404):
                    logger.warning("PDF not accessible (HTTP %s): %s", exc.response.status_code, url)
                    return None
                logger.warning("Attempt %d/%d failed for %s: %s", attempt, self._max_retries, url, exc)
            except httpx.RequestError as exc:
                logger.warning("Attempt %d/%d request error for %s: %s", attempt, self._max_retries, url, exc)
            if attempt < self._max_retries:
                time.sleep(self._delay * attempt)
        logger.error("All %d attempts failed for: %s", self._max_retries, url)
        return None

    def _get_json(self, url: str) -> dict:
        for attempt in range(1, self._max_retries + 1):
            try:
                resp = self._client.get(url)
                resp.raise_for_status()
                return resp.json()
            except Exception as exc:
                logger.warning("Attempt %d/%d failed for %s: %s", attempt, self._max_retries, url, exc)
                if attempt < self._max_retries:
                    time.sleep(self._delay * attempt)
        raise RuntimeError(f"Failed to fetch JSON from {url} after {self._max_retries} attempts")


# ──────────────────────────────────────────────────────────────────
#  Helpers
# ──────────────────────────────────────────────────────────────────

def _parse_date(raw: str | None) -> date | None:
    if not raw:
        return None
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(raw[:len(fmt)], fmt).date()
        except (ValueError, TypeError):
            continue
    return None


def _in_date_range(doc_date: date | None, date_from: date | None, date_to: date | None) -> bool:
    if doc_date is None:
        return True
    if date_from and doc_date < date_from:
        return False
    if date_to and doc_date > date_to:
        return False
    return True


def _html_to_text(html_content: str) -> str:
    """Strip HTML tags and decode entities, returning plain text."""
    # Remove script/style blocks
    text = re.sub(r"<(script|style)[^>]*>.*?</\1>", "", html_content, flags=re.DOTALL | re.IGNORECASE)
    # Replace block-level tags with newlines
    text = re.sub(r"<(br|p|div|h[1-6]|li|tr)[^>]*>", "\n", text, flags=re.IGNORECASE)
    # Remove remaining tags
    text = re.sub(r"<[^>]+>", "", text)
    # Decode HTML entities (&amp; &nbsp; etc.)
    text = html.unescape(text)
    # Normalize whitespace
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()
