"""Azure AI Search integration (HNSW cosine vector index).

In offline mode every operation is a safe no-op; retrieval falls back to the
local lexical scorer in ``pipeline/retrieval.py``.
"""

from __future__ import annotations

import logging
import time
from functools import lru_cache
from typing import Optional

from ..config import get_config
from .llm import embed_text

logger = logging.getLogger(__name__)

EMBED_DIMS = 3072
BATCH_SIZE = 16


@lru_cache(maxsize=1)
def _index_client():
    from azure.core.credentials import AzureKeyCredential
    from azure.search.documents.indexes import SearchIndexClient

    cfg = get_config()
    return SearchIndexClient(cfg.azure_search_endpoint,
                             AzureKeyCredential(cfg.azure_search_api_key))


@lru_cache(maxsize=1)
def _search_client():
    from azure.core.credentials import AzureKeyCredential
    from azure.search.documents import SearchClient

    cfg = get_config()
    return SearchClient(cfg.azure_search_endpoint, cfg.azure_search_index_name,
                        AzureKeyCredential(cfg.azure_search_api_key))


def ensure_index() -> None:
    cfg = get_config()
    if not cfg.has_ai_search:
        return
    from azure.search.documents.indexes.models import (
        HnswAlgorithmConfiguration, HnswParameters, SearchableField, SearchField,
        SearchFieldDataType, SearchIndex, SimpleField, VectorSearch,
        VectorSearchProfile,
    )

    fields = [
        SimpleField(name="id", type=SearchFieldDataType.String, key=True),
        SearchableField(name="content", type=SearchFieldDataType.String,
                        analyzer_name="en.lucene"),
        SimpleField(name="content_type", type=SearchFieldDataType.String, filterable=True),
        SimpleField(name="ticker", type=SearchFieldDataType.String, filterable=True),
        SimpleField(name="accession", type=SearchFieldDataType.String, filterable=True),
        SimpleField(name="form", type=SearchFieldDataType.String, filterable=True),
        SimpleField(name="filing_date", type=SearchFieldDataType.String, filterable=True),
        SimpleField(name="page_number", type=SearchFieldDataType.Int32, filterable=True),
        SearchField(name="embedding",
                    type=SearchFieldDataType.Collection(SearchFieldDataType.Single),
                    searchable=True, vector_search_dimensions=EMBED_DIMS,
                    vector_search_profile_name="hnsw-profile"),
    ]
    vector_search = VectorSearch(
        algorithms=[HnswAlgorithmConfiguration(
            name="hnsw-config",
            parameters=HnswParameters(m=4, ef_construction=400, ef_search=500,
                                      metric="cosine"))],
        profiles=[VectorSearchProfile(name="hnsw-profile",
                                      algorithm_configuration_name="hnsw-config")],
    )
    index = SearchIndex(name=cfg.azure_search_index_name, fields=fields,
                        vector_search=vector_search)
    _index_client().create_or_update_index(index)


def upload_chunks(chunks: list[dict]) -> bool:
    """Embed + upload chunks in batches. No-op (returns False) when offline."""
    cfg = get_config()
    if not cfg.has_ai_search:
        return False
    ensure_index()
    client = _search_client()
    for start in range(0, len(chunks), BATCH_SIZE):
        batch = chunks[start:start + BATCH_SIZE]
        docs = []
        for ch in batch:
            docs.append({**ch, "embedding": embed_text(ch["content"])})
        delay = 2
        for attempt in range(4):
            try:
                client.upload_documents(documents=docs)
                break
            except Exception as exc:  # noqa: BLE001
                if attempt == 3:
                    logger.error("AI Search upload failed: %s", exc)
                    return False
                time.sleep(delay)
                delay *= 2
        time.sleep(1)
    return True


def search_chunks(query: str, ticker: str, top_k: int = 5) -> list[dict]:
    """Hybrid (keyword + vector) search. Returns [] when offline."""
    cfg = get_config()
    if not cfg.has_ai_search:
        return []
    from azure.search.documents.models import VectorizedQuery

    vector = embed_text(query)
    safe_ticker = ticker.replace("'", "''")
    results = _search_client().search(
        search_text=query,
        vector_queries=[VectorizedQuery(vector=vector, k_nearest_neighbors=top_k,
                                        fields="embedding")],
        filter=f"ticker eq '{safe_ticker}'",
        top=top_k,
    )
    out = []
    for r in results:
        out.append({
            "id": r.get("id"),
            "content": r.get("content"),
            "content_type": r.get("content_type"),
            "page_number": r.get("page_number"),
            "score": r.get("@search.score", 0.0),
        })
    return out
