"""Filesystem cache.

Root: ``<data_dir>/<TICKER>/``.  Every ``load_*`` / ``save_*`` function shares a
uniform signature so the backend can later be swapped for Azure Blob storage
without touching call sites.
"""

from __future__ import annotations

import json
import os
from typing import Any, Optional

from ..config import get_config


def _root() -> str:
    return get_config().data_dir


def ticker_dir(ticker: str) -> str:
    path = os.path.join(_root(), ticker.upper())
    os.makedirs(path, exist_ok=True)
    return path


def filing_dir(ticker: str, accession: str) -> str:
    path = os.path.join(ticker_dir(ticker), "filings", accession)
    os.makedirs(path, exist_ok=True)
    return path


# ------------------------------------------------------------------ #
#  Generic helpers                                                   #
# ------------------------------------------------------------------ #
def _read_json(path: str) -> Optional[Any]:
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return None


def _write_json(path: str, data: Any) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2, default=str)


def _read_text(path: str) -> Optional[str]:
    if not os.path.exists(path):
        return None
    with open(path, "r", encoding="utf-8") as fh:
        return fh.read()


def _write_text(path: str, text: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)


# ------------------------------------------------------------------ #
#  SEC data                                                          #
# ------------------------------------------------------------------ #
def load_sec_data(ticker: str) -> Optional[dict]:
    return _read_json(os.path.join(ticker_dir(ticker), "sec_data.json"))


def save_sec_data(ticker: str, data: dict) -> None:
    _write_json(os.path.join(ticker_dir(ticker), "sec_data.json"), data)


# ------------------------------------------------------------------ #
#  Document Intelligence per-filing artifacts                        #
# ------------------------------------------------------------------ #
def load_doc_intelligence_result(ticker: str, accession: str) -> Optional[dict]:
    return _read_json(os.path.join(filing_dir(ticker, accession), "doc_intelligence.json"))


def save_doc_intelligence_result(ticker: str, accession: str, result: dict) -> None:
    _write_json(os.path.join(filing_dir(ticker, accession), "doc_intelligence.json"), result)


def save_filing_text(ticker: str, accession: str, text: str) -> None:
    _write_text(os.path.join(filing_dir(ticker, accession), "document.txt"), text)


def save_filing_meta(ticker: str, accession: str, meta: dict) -> None:
    _write_json(os.path.join(filing_dir(ticker, accession), "meta.json"), meta)


# ------------------------------------------------------------------ #
#  Chunks + AI Search sentinel                                       #
# ------------------------------------------------------------------ #
def load_di_chunks(ticker: str) -> Optional[list[dict]]:
    return _read_json(os.path.join(ticker_dir(ticker), "di_chunks.json"))


def save_di_chunks(ticker: str, chunks: list[dict]) -> None:
    _write_json(os.path.join(ticker_dir(ticker), "di_chunks.json"), chunks)


def has_di_chunks(ticker: str) -> bool:
    return os.path.exists(os.path.join(ticker_dir(ticker), "di_chunks.json"))


# ------------------------------------------------------------------ #
#  Text artifacts                                                    #
# ------------------------------------------------------------------ #
def save_draft_memo(ticker: str, memo: str) -> None:
    _write_text(os.path.join(ticker_dir(ticker), "draft_memo.txt"), memo)


def save_financial_analysis(ticker: str, text: str) -> None:
    _write_text(os.path.join(ticker_dir(ticker), "financial_analysis.txt"), text)


# ------------------------------------------------------------------ #
#  Cached company listing                                            #
# ------------------------------------------------------------------ #
def list_cached_companies() -> list[str]:
    root = _root()
    if not os.path.isdir(root):
        return []
    return sorted(
        name for name in os.listdir(root)
        if os.path.isdir(os.path.join(root, name))
        and os.path.exists(os.path.join(root, name, "sec_data.json"))
    )
