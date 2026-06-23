"""Top-level async pipeline orchestrator.

Five tracked steps: SEC EDGAR -> Document Intelligence -> KPI + indexing ->
analysis agents -> (HITL gate) -> memo composition -> post-processing.
Every step is wrapped so a single failure degrades gracefully.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Optional
from uuid import UUID

from ..config import get_config
from ..core.post_processing import post_process_result
from ..infra import chunker, doc_intelligence, sec_fetcher, storage
from ..infra.ai_search import upload_chunks
from . import kpi_service
from .graph import get_analysis_graph, get_memo_graph
from .task_service import get_task_service

logger = logging.getLogger(__name__)


async def _build_chunks(ticker: str, di_results: list[dict]) -> list[dict]:
    all_chunks: list[dict] = []
    for di in di_results:
        filing = di.get("_filing", {})
        all_chunks.extend(chunker.chunk_di_result(
            di, ticker=ticker, accession=filing.get("accession", "unknown"),
            form=filing.get("form", ""), filing_date=filing.get("date", "")))
    storage.save_di_chunks(ticker, all_chunks)
    return all_chunks


async def run_pipeline(task_id: UUID, ticker: str,
                       fiscal_year: Optional[str] = None,
                       fiscal_period: Optional[str] = None) -> None:
    cfg = get_config()
    svc = get_task_service()
    ticker = ticker.upper()

    def track(msg: str, pct: float, *, done: bool = False,
              awaiting: bool = False, result: Optional[dict] = None) -> None:
        svc.update(task_id, status_log=msg, percentage=pct, is_complete=done,
                   awaiting_approval=awaiting, result=result)

    try:
        # --- Step 1: SEC EDGAR ---------------------------------------
        track("Fetching SEC EDGAR financials", 5.0)
        sec_data = storage.load_sec_data(ticker)
        if not sec_data:
            sec_data = await asyncio.to_thread(
                sec_fetcher.get_quarterly_financials, ticker)
            storage.save_sec_data(ticker, sec_data)
        track("SEC data ready", 15.0)

        company_name = sec_data.get("ticker", ticker)
        cik = sec_data.get("cik")

        # Infer fiscal year/period from the latest filing if not provided
        latest_metric = next(iter(sec_data.get("metrics", {}).values()), {})
        fiscal_year = fiscal_year or (str(latest_metric.get("fiscal_year"))
                                      if latest_metric.get("fiscal_year") else None)
        fiscal_period = fiscal_period or latest_metric.get("fiscal_period")

        # --- Step 2: Document Intelligence ---------------------------
        track("Running Document Intelligence on filings", 20.0)
        di_results: list[dict] = []
        try:
            filings = sec_fetcher.get_latest_10k_10q(cik)
            results = await asyncio.gather(
                *[doc_intelligence.fetch_di_result(ticker, cik, f) for f in filings],
                return_exceptions=True)
            di_results = [r for r in results if isinstance(r, dict)]
        except Exception as exc:  # noqa: BLE001
            logger.warning("Document Intelligence step degraded: %s", exc)
        track("Filings parsed", 48.0)

        # --- Step 3: KPI + indexing (concurrent) ---------------------
        track("Computing KPIs and indexing chunks", 50.0)

        async def _run_kpi():
            return await asyncio.to_thread(
                kpi_service.run_kpi_analysis, ticker, fiscal_year, fiscal_period, sec_data)

        async def _run_index():
            chunks = await _build_chunks(ticker, di_results)
            if cfg.has_ai_search and not storage.has_di_chunks(ticker):
                await asyncio.to_thread(upload_chunks, chunks)
            return chunks

        kpi_data, _ = await asyncio.gather(_run_kpi(), _run_index())
        track("KPIs computed", 55.0)

        # --- Step 4a: Analysis agents --------------------------------
        track("Running analysis agents", 60.0)
        initial_state = {
            "ticker": ticker,
            "company_name": company_name,
            "fiscal_year": fiscal_year,
            "fiscal_period": fiscal_period,
            "sec_data": sec_data,
            "kpi_data": kpi_data,
            "task_id": str(task_id),
            "messages": [],
        }
        analysis_state = await get_analysis_graph().ainvoke(initial_state)
        track("Analysis complete", 80.0)

        # --- Step 4b: HITL gate --------------------------------------
        review_result = post_process_result(analysis_state)
        if not cfg.skip_hitl:
            gate = svc.create_approval_gate(task_id)
            track("Awaiting analyst approval", 80.0, awaiting=True,
                  result=review_result)
            try:
                await asyncio.wait_for(gate.wait(), timeout=cfg.hitl_timeout_seconds)
            except asyncio.TimeoutError:
                logger.info("HITL gate auto-approved after timeout for %s", task_id)
            svc.update(task_id, awaiting_approval=False)
        track("Composing credit memo", 90.0)

        # --- Step 4c: Memo composition -------------------------------
        memo_state = await get_memo_graph().ainvoke(analysis_state)
        analysis_state.update(memo_state)

        # --- Post-processing -----------------------------------------
        result = post_process_result(analysis_state)
        track("Complete", 100.0, done=True, result=result)
        logger.info("Pipeline complete for %s", ticker)

    except Exception as exc:  # noqa: BLE001
        logger.exception("Pipeline failed for %s", ticker)
        svc.mark_failed(task_id, str(exc))
