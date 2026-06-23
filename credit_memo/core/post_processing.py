"""Map the LangGraph state into the final API response shape."""

from __future__ import annotations

import re
from typing import Optional

_SP_RE = re.compile(r"\b(AAA|AA|A|BBB|BB|B|CCC|CC|C|D)[+-]?(?=[^A-Za-z]|$)")
_MOODYS_RE = re.compile(r"\b(Aaa|Aa[123]|A[123]|Baa[123]|Ba[123]|B[123]|Caa[123]?|Ca|C)\b")


def extract_best_credit_rating(text: Optional[str]) -> Optional[str]:
    if not text:
        return None
    m = _SP_RE.search(text)
    if m:
        return m.group(0)
    m = _MOODYS_RE.search(text)
    if m:
        return m.group(0)
    return None


def _debt_to_equity(kpi_data: Optional[dict]) -> Optional[float]:
    if not kpi_data:
        return None
    for kpi in kpi_data.get("computed_kpis", []):
        if kpi["name"] == "debt_to_equity":
            return kpi.get("value")
    return None


def post_process_result(state: dict) -> dict:
    ticker = state.get("ticker")
    company_name = state.get("company_name") or ticker
    qualitative_raw = state.get("qualitative_outlook") or ""
    kpi_data = state.get("kpi_data")

    return {
        "meta": {
            "ticker": ticker,
            "companyName": company_name,
            "fiscalYear": state.get("fiscal_year"),
            "fiscalPeriod": state.get("fiscal_period"),
            "bestCreditRating": extract_best_credit_rating(qualitative_raw)
            or extract_best_credit_rating(state.get("draft_memo")),
            "debtToEquityRatio": _debt_to_equity(kpi_data),
        },
        "financialMetrics": [],  # UI reads financialRemarks + kpi_data
        "financialRemarks": state.get("financial_remarks", ""),
        "financialAnalysis": state.get("financial_analysis", ""),
        "riskAnalysis": state.get("risk_analysis", ""),
        "riskFlags": state.get("risk_flags", []),
        "qualitativeOutlook": state.get("qualitative_outlook", ""),
        "draftMemo": state.get("draft_memo", ""),
        "secData": {"metrics": (state.get("sec_data") or {}).get("metrics", {})},
        "kpi_data": kpi_data,
    }
