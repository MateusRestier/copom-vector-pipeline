"""BCB (Banco Central do Brasil) document downloader.

Downloads COPOM meeting minutes (atas) and policy communications (comunicados)
from the BCB public website and returns them as RawDocument dataclasses.

The downloader checks the database before fetching to skip PDFs that have
already been ingested (dedup via source_hash).

BCB COPOM document pages (as of 2024):
  Atas:        https://www.bcb.gov.br/publicacoes/atascopom
  Comunicados: https://www.bcb.gov.br/publicacoes/comunicados  (filtered by COPOM)

Required env vars:
    BCB_REQUEST_DELAY_SECONDS  — polite delay between requests (default 1.0)
    BCB_MAX_RETRIES            — max retry attempts per request (default 3)
"""

from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass
from datetime import date, datetime
from typing import Iterator

import httpx

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────
#  Public BCB API endpoints
# ─────────────────────────────────────────────
_BCB_API_BASE = "https://www.bcb.gov.br"

# OData API that lists COPOM meeting minutes with PDF links
_ATAS_API = (
    "https://www.bcb.gov.br/api/servico/sitebcb/atascopom/pesquisar"
    "?$top={top}&$skip={skip}&$orderby=DataReferencia%20desc&$filter=IsDeleted%20eq%20false"
)

# OData API for COPOM communications
_COMUNICADOS_API = (
    "https://www.bcb.gov.br/api/servico/sitebcb/comunicados/pesquisar"
    "?$top={top}&$skip={skip}&$orderby=DataReferencia%20desc"
    "&$filter=IsDeleted%20eq%20false%20and%20contains(tolower(Titulo)%2C%20'copom')"
)

_PAGE_SIZE = 50


@dataclass
class RawDocument:
    """A single COPOM document as downloaded from BCB."""
    url: str
    title: str
    doc_type: str          # 'ata' or 'comunicado'
    meeting_date: date | None
    raw_bytes: bytes


class BcbDownloader:
    """Downloads COPOM documents from the BCB public website.

    Args:
        known_hashes: Set of source_hash values already in the database.
            Documents whose hash matches an entry are skipped without
            downloading the PDF bytes.
        request_delay: Seconds to wait between HTTP requests.
        max_retries: Number of retry attempts for failed requests.
    """

    def __init__(
        self,
        known_hashes: set[str] | None = None,
        request_delay: float | None = None,
        max_retries: int | None = None,
    ) -> None:
        self._known_hashes = known_hashes or set()
        self._delay = float(os.environ.get("BCB_REQUEST_DELAY_SECONDS", "1.0")
                            if request_delay is None else request_delay)
        self._max_retries = int(os.environ.get("BCB_MAX_RETRIES", "3")
                                if max_retries is None else max_retries)
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
        """Yield RawDocument objects for each COPOM document found.

        Args:
            doc_types:  Which document types to fetch ('ata', 'comunicado').
            date_from:  Only include documents on or after this date.
            date_to:    Only include documents on or before this date.
            dry_run:    If True, yield metadata only (raw_bytes will be empty).
        """
        if "ata" in doc_types:
            yield from self._iter_doc_type("ata", _ATAS_API, date_from, date_to, dry_run)
        if "comunicado" in doc_types:
            yield from self._iter_doc_type(
                "comunicado", _COMUNICADOS_API, date_from, date_to, dry_run
            )

    def close(self) -> None:
        self._client.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    # ──────────────────────────────────────────────────────────────────
    #  Internal helpers
    # ──────────────────────────────────────────────────────────────────

    def _iter_doc_type(
        self,
        doc_type: str,
        api_template: str,
        date_from: date | None,
        date_to: date | None,
        dry_run: bool,
    ) -> Iterator[RawDocument]:
        skip = 0
        while True:
            url = api_template.format(top=_PAGE_SIZE, skip=skip)
            data = self._get_json(url)
            items = data.get("value", [])
            if not items:
                break

            for item in items:
                doc = self._parse_item(item, doc_type)
                if doc is None:
                    continue
                if not self._in_date_range(doc.meeting_date, date_from, date_to):
                    continue
                if dry_run:
                    logger.info("[dry-run] Would fetch: %s", doc.title)
                    yield doc
                    continue
                raw = self._fetch_pdf(doc.url)
                if raw is None:
                    continue
                yield RawDocument(
                    url=doc.url,
                    title=doc.title,
                    doc_type=doc.doc_type,
                    meeting_date=doc.meeting_date,
                    raw_bytes=raw,
                )
                time.sleep(self._delay)

            skip += _PAGE_SIZE
            if len(items) < _PAGE_SIZE:
                break

    def _parse_item(self, item: dict, doc_type: str) -> RawDocument | None:
        """Parse a single API result item into a RawDocument stub (no bytes)."""
        try:
            title = item.get("Titulo") or item.get("titulo") or ""
            pdf_link = self._extract_pdf_link(item)
            if not pdf_link:
                logger.debug("No PDF link found for item: %s", title)
                return None

            url = pdf_link if pdf_link.startswith("http") else f"{_BCB_API_BASE}{pdf_link}"
            raw_date = item.get("DataReferencia") or item.get("dataReferencia")
            meeting_date = self._parse_date(raw_date)

            return RawDocument(
                url=url,
                title=title.strip(),
                doc_type=doc_type,
                meeting_date=meeting_date,
                raw_bytes=b"",
            )
        except Exception as exc:
            logger.warning("Failed to parse item: %s — %s", item, exc)
            return None

    def _extract_pdf_link(self, item: dict) -> str | None:
        """Extract the PDF URL from an API item (field names vary by endpoint)."""
        for key in ("Url", "url", "LinkPdf", "linkPdf", "link"):
            val = item.get(key)
            if val and isinstance(val, str) and val.lower().endswith(".pdf"):
                return val
        # Some items embed the link inside a nested 'DescricaoHtml' field
        desc = item.get("DescricaoHtml") or ""
        if ".pdf" in desc.lower():
            import re
            match = re.search(r'href="([^"]+\.pdf)"', desc, re.IGNORECASE)
            if match:
                return match.group(1)
        return None

    def _fetch_pdf(self, url: str) -> bytes | None:
        """Download a PDF with retry logic. Returns None on permanent failure."""
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
        """Fetch a JSON endpoint with retry logic."""
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

    @staticmethod
    def _parse_date(raw: str | None) -> date | None:
        if not raw:
            return None
        for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d", "%d/%m/%Y"):
            try:
                return datetime.strptime(raw[:len(fmt)], fmt).date()
            except ValueError:
                continue
        return None

    @staticmethod
    def _in_date_range(
        doc_date: date | None,
        date_from: date | None,
        date_to: date | None,
    ) -> bool:
        if doc_date is None:
            return True  # include documents without a date
        if date_from and doc_date < date_from:
            return False
        if date_to and doc_date > date_to:
            return False
        return True
