"""Application configuration.

All settings are loaded from environment variables (optionally via a ``.env``
file).  Every Azure-related field is optional so the application can boot and
run in *offline / mock mode* without any cloud credentials.  When real keys are
supplied the corresponding integrations light up automatically.
"""

from __future__ import annotations

import os
from functools import lru_cache
from typing import Optional

from dotenv import load_dotenv
from pydantic import BaseModel

load_dotenv()


def _clean_openai_endpoint(value: Optional[str]) -> Optional[str]:
    """Strip a trailing ``/openai`` (or ``/openai/...``) path from the endpoint."""
    if not value:
        return value
    value = value.strip().rstrip("/")
    lowered = value.lower()
    idx = lowered.find("/openai")
    if idx != -1:
        value = value[:idx]
    return value


def _bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


class Config(BaseModel):
    # --- server ---------------------------------------------------------
    host: str = "127.0.0.1"
    port: int = 8001
    debug: bool = False
    log_level: str = "info"

    # --- Azure OpenAI ---------------------------------------------------
    azure_openai_api_key: Optional[str] = None
    azure_openai_endpoint: Optional[str] = None
    azure_openai_api_version: str = "2024-10-21"
    azure_openai_deployment_name: Optional[str] = None
    azure_openai_mini_deployment: Optional[str] = None
    azure_openai_embedding_deployment: str = "text-embedding-3-large"

    # --- Azure Document Intelligence ------------------------------------
    document_intelligence_endpoint: Optional[str] = None
    document_intelligence_key: Optional[str] = None

    # --- Azure AI Search ------------------------------------------------
    azure_search_endpoint: Optional[str] = None
    azure_search_api_key: Optional[str] = None
    azure_search_index_name: str = "credit-memo-chunks"

    # --- Azure SQL ------------------------------------------------------
    azure_sql_server: Optional[str] = None
    azure_sql_database: Optional[str] = None
    azure_sql_conn_string: Optional[str] = None

    # --- Azure Blob (optional storage backend) --------------------------
    azure_storage_connection_string: Optional[str] = None
    azure_blob_container: str = "raw-documents"

    # --- misc -----------------------------------------------------------
    sec_user_agent: str = "CreditMemo Research admin@example.com"
    skip_hitl: bool = False
    hitl_timeout_seconds: int = 3600
    data_dir: str = "data"

    # ------------------------------------------------------------------ #
    #  Derived capability flags                                          #
    # ------------------------------------------------------------------ #
    @property
    def has_openai(self) -> bool:
        return bool(self.azure_openai_api_key and self.azure_openai_endpoint
                    and self.azure_openai_deployment_name)

    @property
    def has_doc_intelligence(self) -> bool:
        return bool(self.document_intelligence_endpoint and self.document_intelligence_key)

    @property
    def has_ai_search(self) -> bool:
        return bool(self.azure_search_endpoint and self.azure_search_api_key)

    @property
    def has_sql(self) -> bool:
        return bool(self.azure_sql_conn_string or (self.azure_sql_server and self.azure_sql_database))

    @property
    def mock_mode(self) -> bool:
        """True when no real LLM is configured -> use deterministic stubs."""
        if _bool("FORCE_MOCK_MODE"):
            return True
        return not self.has_openai


@lru_cache(maxsize=1)
def get_config() -> Config:
    return Config(
        host=os.getenv("HOST", "127.0.0.1"),
        port=int(os.getenv("PORT", "8001")),
        debug=_bool("DEBUG"),
        log_level=os.getenv("LOG_LEVEL", "info"),
        azure_openai_api_key=os.getenv("AZURE_OPENAI_API_KEY"),
        azure_openai_endpoint=_clean_openai_endpoint(os.getenv("AZURE_OPENAI_ENDPOINT")),
        azure_openai_api_version=os.getenv("AZURE_OPENAI_API_VERSION", "2024-10-21"),
        azure_openai_deployment_name=os.getenv("AZURE_OPENAI_DEPLOYMENT_NAME"),
        azure_openai_mini_deployment=os.getenv("AZURE_OPENAI_MINI_DEPLOYMENT"),
        azure_openai_embedding_deployment=os.getenv(
            "AZURE_OPENAI_EMBEDDING_DEPLOYMENT", "text-embedding-3-large"),
        document_intelligence_endpoint=os.getenv("DOCUMENT_INTELLIGENCE_ENDPOINT"),
        document_intelligence_key=os.getenv("DOCUMENT_INTELLIGENCE_KEY"),
        azure_search_endpoint=os.getenv("AZURE_SEARCH_ENDPOINT"),
        azure_search_api_key=os.getenv("AZURE_SEARCH_API_KEY"),
        azure_search_index_name=os.getenv("AZURE_SEARCH_INDEX_NAME", "credit-memo-chunks"),
        azure_sql_server=os.getenv("AZURE_SQL_SERVER"),
        azure_sql_database=os.getenv("AZURE_SQL_DATABASE"),
        azure_sql_conn_string=os.getenv("AZURE_SQL_CONN_STRING"),
        azure_storage_connection_string=os.getenv("AZURE_STORAGE_CONNECTION_STRING"),
        azure_blob_container=os.getenv("AZURE_BLOB_CONTAINER", "raw-documents"),
        sec_user_agent=os.getenv("SEC_USER_AGENT", "CreditMemo Research admin@example.com"),
        skip_hitl=_bool("SKIP_HITL"),
        hitl_timeout_seconds=int(os.getenv("HITL_TIMEOUT_SECONDS", "3600")),
        data_dir=os.getenv("DATA_DIR", "data"),
    )
