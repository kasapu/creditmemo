"""LLM access layer.

Exposes a single async ``complete()`` coroutine used by every agent.  When real
Azure OpenAI credentials are configured it calls ``AzureChatOpenAI``; otherwise
it returns deterministic, well-formed mock output so the whole pipeline runs
offline.  Embeddings follow the same real / mock split.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import struct
from functools import lru_cache
from typing import Optional

from ..config import get_config

logger = logging.getLogger(__name__)


# ------------------------------------------------------------------ #
#  Real Azure OpenAI clients (lazy)                                  #
# ------------------------------------------------------------------ #
@lru_cache(maxsize=1)
def get_chat_llm():
    from langchain_openai import AzureChatOpenAI

    cfg = get_config()
    return AzureChatOpenAI(
        azure_endpoint=cfg.azure_openai_endpoint,
        azure_deployment=cfg.azure_openai_deployment_name,
        api_key=cfg.azure_openai_api_key,
        api_version=cfg.azure_openai_api_version,
        temperature=0.2,
    )


@lru_cache(maxsize=1)
def get_chat_llm_mini():
    from langchain_openai import AzureChatOpenAI

    cfg = get_config()
    deployment = cfg.azure_openai_mini_deployment or cfg.azure_openai_deployment_name
    return AzureChatOpenAI(
        azure_endpoint=cfg.azure_openai_endpoint,
        azure_deployment=deployment,
        api_key=cfg.azure_openai_api_key,
        api_version=cfg.azure_openai_api_version,
        temperature=0.1,
    )


def _is_rate_limit(exc: Exception) -> bool:
    msg = str(exc).lower()
    return "429" in msg or "rate limit" in msg or "too many requests" in msg


# ------------------------------------------------------------------ #
#  Public completion API                                             #
# ------------------------------------------------------------------ #
async def complete(
    system_prompt: str,
    user_prompt: str,
    *,
    kind: str = "generic",
    context: Optional[dict] = None,
    mini: bool = False,
    max_retries: int = 5,
) -> str:
    """Return the model completion text.

    ``kind`` and ``context`` are only used to shape deterministic output in mock
    mode; they are ignored when a real model answers.
    """
    cfg = get_config()
    if cfg.mock_mode:
        return _mock_completion(kind, context or {})

    from langchain_core.messages import HumanMessage, SystemMessage

    llm = get_chat_llm_mini() if mini else get_chat_llm()
    delay = 10
    for attempt in range(max_retries):
        try:
            resp = await llm.ainvoke([
                SystemMessage(content=system_prompt),
                HumanMessage(content=user_prompt),
            ])
            return resp.content
        except Exception as exc:  # noqa: BLE001
            if not _is_rate_limit(exc) or attempt == max_retries - 1:
                logger.error("LLM call failed (%s): %s", kind, exc)
                raise
            wait = min(delay * (2 ** attempt), 120)
            logger.warning("Rate limited (%s), retry in %ss", kind, wait)
            await asyncio.sleep(wait)
    raise RuntimeError("unreachable")


# ------------------------------------------------------------------ #
#  Embeddings                                                        #
# ------------------------------------------------------------------ #
@lru_cache(maxsize=1)
def _get_embedder():
    from langchain_openai import AzureOpenAIEmbeddings

    cfg = get_config()
    return AzureOpenAIEmbeddings(
        azure_endpoint=cfg.azure_openai_endpoint,
        azure_deployment=cfg.azure_openai_embedding_deployment,
        api_key=cfg.azure_openai_api_key,
        api_version=cfg.azure_openai_api_version,
    )


def embed_text(text: str, dims: int = 3072) -> list[float]:
    """Return an embedding vector. Deterministic hash-based vector in mock mode."""
    cfg = get_config()
    if cfg.mock_mode:
        return _mock_embedding(text, dims)
    return _get_embedder().embed_query(text[:8000])


def _mock_embedding(text: str, dims: int) -> list[float]:
    """Cheap deterministic pseudo-embedding (good enough for local retrieval)."""
    vec = [0.0] * dims
    for token in text.lower().split():
        h = int(hashlib.md5(token.encode()).hexdigest(), 16)
        vec[h % dims] += 1.0
    norm = sum(v * v for v in vec) ** 0.5 or 1.0
    return [v / norm for v in vec]


# ------------------------------------------------------------------ #
#  Deterministic mock completions                                    #
# ------------------------------------------------------------------ #
def _kpi_lines(context: dict, limit: int = 8) -> list[str]:
    kpi = context.get("kpi_data") or {}
    out: list[str] = []
    for item in (kpi.get("computed_kpis") or [])[:limit]:
        label = item.get("label", item.get("name", ""))
        val = item.get("display", item.get("value"))
        if val is not None:
            out.append(f"<t>**{label}:** **{val}**")
    return out


def _mock_completion(kind: str, context: dict) -> str:
    company = context.get("company_name") or context.get("ticker") or "the company"
    fy = context.get("fiscal_year") or ""
    fp = context.get("fiscal_period") or ""
    period = f"FY{fy} {fp}".strip()

    if kind == "financial_remarks":
        lines = _kpi_lines(context)
        body = "\n".join(lines) if lines else "<t>KPI data unavailable for this period."
        return (
            f"**Financial Remarks ({period}):**\n{body}\n"
            f"<t>Overall, **{company}** demonstrates a financial profile consistent "
            f"with the computed KPI set above. All figures are sourced directly from "
            f"the structured KPI model (no estimated values)."
        )

    if kind == "risk_analysis":
        ev = (context.get("evidence") or "")[:400].replace("\n", " ")
        return (
            f"**Risk Assessment ({period}):**\n"
            f"<t>**Leverage:** Debt capacity is evaluated against liquid assets and "
            f"operating cash flow; coverage signals are derived from the KPI model.\n"
            f"<t>**Liquidity:** Current and quick ratios indicate the near-term ability "
            f"of **{company}** to meet obligations.\n"
            f"<t>**Operational / Market:** Sector concentration and macro sensitivity "
            f"are the primary qualitative risk vectors.\n"
            f"<t>**Filing evidence:** {ev or 'No filing excerpt available offline.'}"
        )

    if kind == "qualitative_outlook":
        ev = (context.get("evidence") or "")[:400].replace("\n", " ")
        return (
            f"**Business Outlook ({period}):**\n"
            f"<t>**{company}** maintains its strategic positioning within its core "
            f"markets with a multi-year plan focused on revenue durability and margin "
            f"discipline.\n"
            f"<t>**Management commentary:** {ev or 'No MD&A excerpt available offline.'}\n"
            f"<t>**Indicative credit rating:** **BBB** (illustrative, offline mode)."
        )

    if kind == "memo_composer":
        fin = context.get("financial_remarks", "")
        risk = context.get("risk_analysis", "")
        qual = context.get("qualitative_outlook", "")
        return (
            f"**Executive Summary:**\n"
            f"<t>This credit memo for **{company}** ({period}) synthesizes the "
            f"financial, risk, and qualitative analyses produced by the pipeline.\n\n"
            f"**Financial Performance:**\n{fin}\n\n"
            f"**Risk Assessment:**\n{risk}\n\n"
            f"**Business Outlook:**\n{qual}\n\n"
            f"**Credit Recommendation:**\n"
            f"<t>Based on the synthesized analysis, a **BBB** indicative rating with a "
            f"**Stable** outlook is recommended (illustrative, offline mode). Final "
            f"determination is subject to analyst review."
        )

    return f"**Analysis ({period}):**\n<t>Generated analysis for **{company}**."
