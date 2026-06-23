"""LangGraph node functions and LLM analysis agents.

Each agent is grounded only in the evidence relevant to its task: financial
remarks from the KPI table, risk from KPIs + risk-query evidence, qualitative
from MD&A-style evidence. The memo composer synthesizes the three outputs only.
"""

from __future__ import annotations

import logging
import re

from ..core.state import CreditMemoState
from ..infra import storage
from ..infra.llm import complete
from ..prompts.agent_prompts import (
    FINANCIAL_REMARKS_PROMPT,
    MEMO_COMPOSER_PROMPT,
    QUALITATIVE_OUTLOOK_PROMPT,
    RISK_ANALYSIS_PROMPT,
)
from . import kpi_context, kpi_service, retrieval

logger = logging.getLogger(__name__)


# ------------------------------------------------------------------ #
#  Output normalization                                              #
# ------------------------------------------------------------------ #
def _normalize_for_ui(text: str) -> str:
    if not text:
        return ""
    # strip wrapping code fences
    text = re.sub(r"^```[a-zA-Z]*\n?", "", text.strip())
    text = re.sub(r"\n?```$", "", text)
    out_lines = []
    for line in text.splitlines():
        stripped = line.strip()
        if re.match(r"^[-*]\s+", stripped):
            stripped = "<t>" + re.sub(r"^[-*]\s+", "", stripped)
        stripped = re.sub(r"^#{1,6}\s*", "", stripped)
        if stripped == "---":
            continue
        out_lines.append(stripped)
    text = "\n".join(out_lines)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _ctx(state: CreditMemoState, **extra) -> dict:
    base = {
        "ticker": state.get("ticker"),
        "company_name": state.get("company_name") or state.get("ticker"),
        "fiscal_year": state.get("fiscal_year"),
        "fiscal_period": state.get("fiscal_period"),
        "kpi_data": state.get("kpi_data"),
    }
    base.update(extra)
    return base


# ------------------------------------------------------------------ #
#  Data nodes (used by full_graph / CLI graph)                        #
# ------------------------------------------------------------------ #
async def sec_agent(state: CreditMemoState) -> dict:
    from ..infra import sec_fetcher

    ticker = state["ticker"]
    sec_data = state.get("sec_data") or storage.load_sec_data(ticker)
    if not sec_data:
        sec_data = sec_fetcher.get_quarterly_financials(ticker)
        storage.save_sec_data(ticker, sec_data)
    kpi_data = state.get("kpi_data") or kpi_service.run_kpi_analysis(
        ticker, state.get("fiscal_year"), state.get("fiscal_period"), sec_data)
    return {"sec_data": sec_data, "kpi_data": kpi_data}


async def parse_node(state: CreditMemoState) -> dict:
    chunks = storage.load_di_chunks(state["ticker"]) or []
    document_text = state.get("document_text") or "\n".join(
        c.get("content", "") for c in chunks[:50])
    return {"chunks": [c.get("content", "") for c in chunks], "document_text": document_text}


# ------------------------------------------------------------------ #
#  Analysis agents                                                   #
# ------------------------------------------------------------------ #
async def financial_agent(state: CreditMemoState) -> dict:
    """Deterministic rule-based summary + risk flags (no LLM)."""
    kpi = state.get("kpi_data") or {}
    vals = kpi.get("_values") or {}
    flags: list[str] = []
    cr = next((k.get("value") for k in kpi.get("computed_kpis", [])
               if k["name"] == "current_ratio"), None)
    de = next((k.get("value") for k in kpi.get("computed_kpis", [])
               if k["name"] == "debt_to_equity"), None)
    if cr is not None and cr < 1:
        flags.append(f"Current ratio below 1.0 ({cr:.2f}x)")
    if de is not None and de > 2:
        flags.append(f"Elevated debt/equity ({de:.2f}x)")
    if (vals.get("net_income") or 0) < 0:
        flags.append("Negative net income")
    summary = kpi_context.format_kpi_table(kpi)
    storage.save_financial_analysis(state["ticker"], summary)
    return {"financial_analysis": summary, "risk_flags": flags}


async def financial_remarks_agent(state: CreditMemoState) -> dict:
    kpi_table = kpi_context.format_kpi_table(state.get("kpi_data"))
    user = f"KPI TABLE:\n{kpi_table}\n\nWrite the Financial Remarks section."
    text = await complete(FINANCIAL_REMARKS_PROMPT, user,
                          kind="financial_remarks", context=_ctx(state))
    return {"financial_remarks": _normalize_for_ui(text)}


async def risk_agent(state: CreditMemoState) -> dict:
    kpi_table = kpi_context.format_kpi_table(state.get("kpi_data"))
    snapshot = kpi_context.build_company_profile_snapshot(state.get("kpi_data"))
    evidence = retrieval.gather_evidence(retrieval.RISK_QUERIES, state["ticker"])
    user = (f"KPI TABLE:\n{kpi_table}\n\n{snapshot}\n\n"
            f"FILING EVIDENCE:\n{evidence[:6000]}\n\nWrite the Risk Assessment.")
    text = await complete(RISK_ANALYSIS_PROMPT, user, kind="risk_analysis",
                          context=_ctx(state, evidence=evidence))
    return {"risk_analysis": _normalize_for_ui(text)}


async def qualitative_agent(state: CreditMemoState) -> dict:
    kpi_table = kpi_context.format_kpi_table(state.get("kpi_data"))
    evidence = retrieval.gather_evidence(retrieval.QUALITATIVE_QUERIES, state["ticker"])
    user = (f"FILING EVIDENCE:\n{evidence[:6000]}\n\n"
            f"KPI TABLE (tone only, do not quote):\n{kpi_table}\n\n"
            f"Write the Business Outlook.")
    text = await complete(QUALITATIVE_OUTLOOK_PROMPT, user, kind="qualitative_outlook",
                          context=_ctx(state, evidence=evidence))
    norm = _normalize_for_ui(text)
    return {"qualitative_outlook": norm, "qualitative_analysis": norm}


async def memo_composer_agent(state: CreditMemoState) -> dict:
    fin = state.get("financial_remarks", "")
    risk = state.get("risk_analysis", "")
    qual = state.get("qualitative_outlook", "")
    user = (f"FINANCIAL REMARKS:\n{fin}\n\nRISK ASSESSMENT:\n{risk}\n\n"
            f"BUSINESS OUTLOOK:\n{qual}\n\nCompose the final credit memo.")
    text = await complete(MEMO_COMPOSER_PROMPT, user, kind="memo_composer",
                          context=_ctx(state, financial_remarks=fin,
                                       risk_analysis=risk, qualitative_outlook=qual))
    memo = _normalize_for_ui(text)
    storage.save_draft_memo(state["ticker"], memo)
    return {"draft_memo": memo}


async def supervisor_node(state: CreditMemoState) -> dict:
    """Terminal pass-through node (placeholder for future routing logic)."""
    return {}
