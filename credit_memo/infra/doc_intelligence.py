"""Azure Document Intelligence integration with an offline fallback.

Real path: download the SEC ``.htm`` (with a ``User-Agent``), render it to PDF
via headless Playwright/Chromium, then run the ``prebuilt-layout`` model.

Offline path: download the ``.htm`` and extract clean plain text with
BeautifulSoup.  The serialized result shares the same schema either way.
"""

from __future__ import annotations

import asyncio
import logging
import os
import tempfile
from typing import Optional

from ..config import get_config
from . import sec_fetcher

logger = logging.getLogger(__name__)

# In-flight de-duplication: concurrent requests for the same accession share one
# computation rather than calling Azure DI twice.
_DI_INFLIGHT: dict[str, "asyncio.Future"] = {}


def _empty_result(full_text: str = "") -> dict:
    return {"full_text": full_text, "tables": [], "paragraphs": []}


async def _render_to_pdf(html_text: str) -> bytes:
    from playwright.async_api import async_playwright

    with tempfile.NamedTemporaryFile("w", suffix=".html", delete=False, encoding="utf-8") as tmp:
        tmp.write(html_text)
        tmp_path = tmp.name
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch()
            page = await browser.new_page()
            await page.goto(f"file://{tmp_path}", wait_until="domcontentloaded")
            pdf_bytes = await page.pdf(format="A4")
            await browser.close()
        return pdf_bytes
    finally:
        os.unlink(tmp_path)


async def _analyze_with_azure(pdf_bytes: bytes) -> dict:
    from azure.ai.documentintelligence import DocumentIntelligenceClient
    from azure.ai.documentintelligence.models import AnalyzeDocumentRequest
    from azure.core.credentials import AzureKeyCredential

    cfg = get_config()
    client = DocumentIntelligenceClient(
        endpoint=cfg.document_intelligence_endpoint,
        credential=AzureKeyCredential(cfg.document_intelligence_key),
    )

    def _run() -> dict:
        poller = client.begin_analyze_document(
            "prebuilt-layout",
            AnalyzeDocumentRequest(bytes_source=pdf_bytes),
        )
        result = poller.result()
        tables = []
        for tbl in (result.tables or []):
            tables.append({
                "row_count": tbl.row_count,
                "column_count": tbl.column_count,
                "page_number": (tbl.bounding_regions[0].page_number
                                if tbl.bounding_regions else None),
                "cells": [{
                    "row": c.row_index,
                    "col": c.column_index,
                    "content": c.content,
                    "kind": getattr(c, "kind", None),
                    "row_span": getattr(c, "row_span", 1) or 1,
                    "col_span": getattr(c, "column_span", 1) or 1,
                } for c in tbl.cells],
            })
        paragraphs = [{
            "content": p.content,
            "role": getattr(p, "role", None),
            "page_number": (p.bounding_regions[0].page_number
                            if getattr(p, "bounding_regions", None) else None),
        } for p in (result.paragraphs or [])]
        return {"full_text": result.content or "", "tables": tables, "paragraphs": paragraphs}

    return await asyncio.to_thread(_run)


async def _compute_di_result(ticker: str, cik: str, accession: str,
                             primary_doc: str) -> dict:
    """Run DI (real or offline) for a single filing."""
    cfg = get_config()
    html = await asyncio.to_thread(
        sec_fetcher.fetch_filing_html, cik, accession, primary_doc)

    if cfg.has_doc_intelligence:
        try:
            pdf_bytes = await _render_to_pdf(html)
            return await _analyze_with_azure(pdf_bytes)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Azure DI failed for %s, falling back to text: %s",
                           accession, exc)

    # Offline / fallback: plain-text extraction with synthetic paragraphs.
    text = sec_fetcher.html_to_text(html)
    paragraphs = [{"content": para.strip(), "role": None, "page_number": None}
                  for para in text.split("\n") if para.strip()]
    return {"full_text": text, "tables": [], "paragraphs": paragraphs}


async def fetch_di_result(ticker: str, cik: str, filing: dict) -> dict:
    """Cached + de-duplicated DI fetch for one filing."""
    from . import storage

    accession = filing["accession"]
    # Layer 1: disk cache
    cached = storage.load_doc_intelligence_result(ticker, accession)
    if cached:
        return cached

    # Layer 2: in-flight de-dup
    if accession in _DI_INFLIGHT:
        return await _DI_INFLIGHT[accession]

    loop = asyncio.get_event_loop()
    fut: "asyncio.Future" = loop.create_future()
    _DI_INFLIGHT[accession] = fut
    try:
        result = await _compute_di_result(
            ticker, cik, accession, filing.get("primary_doc"))
        result["_filing"] = {
            "form": filing.get("form"),
            "date": filing.get("date"),
            "accession": accession,
            "primary_doc": filing.get("primary_doc"),
        }
        storage.save_doc_intelligence_result(ticker, accession, result)
        storage.save_filing_text(ticker, accession, result.get("full_text", ""))
        storage.save_filing_meta(ticker, accession, result["_filing"])
        fut.set_result(result)
        return result
    except Exception as exc:
        fut.set_exception(exc)
        raise
    finally:
        _DI_INFLIGHT.pop(accession, None)
