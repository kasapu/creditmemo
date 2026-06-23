"""Evidence retrieval with graceful fallback.

Azure AI Search (hybrid keyword + vector) when configured; otherwise a local
lexical scorer over the cached ``di_chunks.json``.
"""

from __future__ import annotations

import re
from typing import Optional

from ..config import get_config
from ..infra import ai_search, storage

MIN_SCORE = 0.01

FINANCIAL_QUERIES = [
    "income statement revenue net income",
    "balance sheet total assets liabilities equity",
    "cash flow operating investing financing",
    "long-term debt borrowings leverage",
    "gross margin operating margin profitability",
    "liquidity working capital",
    "filing period fiscal year results",
]

QUALITATIVE_QUERIES = [
    "company overview business description",
    "products and services segments",
    "recent developments strategy",
    "management discussion and analysis outlook",
    "competition market position",
    "regulatory environment compliance",
    "acquisitions investments",
    "research and development innovation",
]

RISK_QUERIES = [
    "credit risk default risk",
    "liquidity risk funding",
    "legal proceedings litigation",
    "operational risk supply chain",
    "market risk interest rate foreign exchange",
    "concentration risk customers suppliers",
    "debt covenants obligations",
    "macroeconomic conditions",
    "cybersecurity data risk",
    "going concern uncertainty",
]


def _tokenize(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", text.lower())


def _lexical_score(query: str, content: str) -> float:
    q = set(_tokenize(query))
    if not q:
        return 0.0
    c = _tokenize(content)
    if not c:
        return 0.0
    overlap = sum(1 for w in c if w in q)
    return overlap / (len(c) ** 0.5)


def _local_search(query: str, ticker: str, top_k: int) -> list[dict]:
    chunks = storage.load_di_chunks(ticker) or []
    scored = []
    for ch in chunks:
        score = _lexical_score(query, ch.get("content", ""))
        if score > 0:
            scored.append({**ch, "score": score})
    scored.sort(key=lambda x: x["score"], reverse=True)
    return scored[:top_k]


def search(query: str, ticker: str, top_k: int = 5) -> list[dict]:
    cfg = get_config()
    if cfg.has_ai_search:
        results = ai_search.search_chunks(query, ticker, top_k)
        return [r for r in results if r.get("score", 0) >= MIN_SCORE]
    return _local_search(query, ticker, top_k)


def gather_evidence(queries: list[str], ticker: str, per_query: int = 3,
                    max_total: int = 12) -> str:
    """Run a set of sub-queries, dedupe by id, return concatenated text."""
    seen: set[str] = set()
    collected: list[dict] = []
    for q in queries:
        for hit in search(q, ticker, per_query):
            cid = hit.get("id") or hit.get("content", "")[:40]
            if cid in seen:
                continue
            seen.add(cid)
            collected.append(hit)
            if len(collected) >= max_total:
                break
        if len(collected) >= max_total:
            break
    return "\n\n".join(h.get("content", "") for h in collected)
