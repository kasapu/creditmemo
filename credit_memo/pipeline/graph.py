"""Compiled LangGraph state graphs.

* ``graph``          minimal dev/CLI graph
* ``analysis_graph`` HITL step 1 (stops before memo composition)
* ``memo_graph``     HITL step 2 (runs after approval)
* ``full_graph``     end-to-end, no HITL pause
"""

from __future__ import annotations

from functools import lru_cache

from langgraph.graph import END, START, StateGraph

from ..core.state import CreditMemoState
from . import agents


def _build_analysis_graph():
    g = StateGraph(CreditMemoState)
    g.add_node("financial_agent", agents.financial_agent)
    g.add_node("financial_remarks_agent", agents.financial_remarks_agent)
    g.add_node("risk_agent", agents.risk_agent)
    g.add_node("qualitative_agent", agents.qualitative_agent)
    g.add_node("supervisor_node", agents.supervisor_node)

    g.add_edge(START, "financial_agent")
    # fan-out (parallel branches)
    g.add_edge("financial_agent", "financial_remarks_agent")
    g.add_edge("financial_agent", "risk_agent")
    g.add_edge("financial_agent", "qualitative_agent")
    # fan-in
    g.add_edge("financial_remarks_agent", "supervisor_node")
    g.add_edge("risk_agent", "supervisor_node")
    g.add_edge("qualitative_agent", "supervisor_node")
    g.add_edge("supervisor_node", END)
    return g.compile()


def _build_memo_graph():
    g = StateGraph(CreditMemoState)
    g.add_node("memo_composer_agent", agents.memo_composer_agent)
    g.add_edge(START, "memo_composer_agent")
    g.add_edge("memo_composer_agent", END)
    return g.compile()


def _build_full_graph():
    g = StateGraph(CreditMemoState)
    g.add_node("sec_agent", agents.sec_agent)
    g.add_node("parse_node", agents.parse_node)
    g.add_node("financial_agent", agents.financial_agent)
    g.add_node("financial_remarks_agent", agents.financial_remarks_agent)
    g.add_node("risk_agent", agents.risk_agent)
    g.add_node("qualitative_agent", agents.qualitative_agent)
    g.add_node("memo_composer_agent", agents.memo_composer_agent)
    g.add_node("supervisor_node", agents.supervisor_node)

    g.add_edge(START, "sec_agent")
    g.add_edge("sec_agent", "parse_node")
    g.add_edge("parse_node", "financial_agent")
    g.add_edge("financial_agent", "financial_remarks_agent")
    g.add_edge("financial_agent", "risk_agent")
    g.add_edge("financial_agent", "qualitative_agent")
    g.add_edge("financial_remarks_agent", "memo_composer_agent")
    g.add_edge("risk_agent", "memo_composer_agent")
    g.add_edge("qualitative_agent", "memo_composer_agent")
    g.add_edge("memo_composer_agent", "supervisor_node")
    g.add_edge("supervisor_node", END)
    return g.compile()


def _build_min_graph():
    g = StateGraph(CreditMemoState)
    g.add_node("sec_agent", agents.sec_agent)
    g.add_node("parse_node", agents.parse_node)
    g.add_node("financial_agent", agents.financial_agent)
    g.add_node("supervisor_node", agents.supervisor_node)
    g.add_edge(START, "sec_agent")
    g.add_edge("sec_agent", "parse_node")
    g.add_edge("parse_node", "financial_agent")
    g.add_edge("financial_agent", "supervisor_node")
    g.add_edge("supervisor_node", END)
    return g.compile()


@lru_cache(maxsize=1)
def get_analysis_graph():
    return _build_analysis_graph()


@lru_cache(maxsize=1)
def get_memo_graph():
    return _build_memo_graph()


@lru_cache(maxsize=1)
def get_full_graph():
    return _build_full_graph()


@lru_cache(maxsize=1)
def get_graph():
    return _build_min_graph()
