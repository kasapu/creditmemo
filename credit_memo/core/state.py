"""LangGraph shared state for the credit-memo pipeline."""

from __future__ import annotations

from typing import Annotated, Optional, TypedDict

try:  # langgraph is a core dependency, but keep the import resilient
    from langgraph.graph.message import add_messages
except Exception:  # pragma: no cover - fallback for minimal installs
    def add_messages(left, right):  # type: ignore
        return (left or []) + (right or [])


class CreditMemoState(TypedDict, total=False):
    # --- input ---------------------------------------------------------
    ticker: Optional[str]
    company_name: Optional[str]
    document_text: str
    fiscal_year: Optional[str]
    fiscal_period: Optional[str]

    # --- data layer ----------------------------------------------------
    sec_data: Optional[dict]
    di_results: list[dict]
    kpi_data: Optional[dict]
    search_indexed: bool

    # --- intermediate --------------------------------------------------
    chunks: list[str]

    # --- agent outputs -------------------------------------------------
    financial_analysis: str
    financial_remarks: str
    risk_analysis: str
    qualitative_outlook: str
    qualitative_analysis: str
    risk_flags: list[str]

    # --- final ---------------------------------------------------------
    draft_memo: str

    # --- HITL ----------------------------------------------------------
    hitl_approved: bool
    hitl_pending: bool

    # --- task tracking -------------------------------------------------
    task_id: Optional[str]

    # --- message log ---------------------------------------------------
    messages: Annotated[list, add_messages]
