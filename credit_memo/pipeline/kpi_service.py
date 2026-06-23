"""KPI computation engine.

Two sources of base metrics:

* **Azure SQL** (``sec_financial_facts``) when configured -- the production path.
* **SEC EDGAR XBRL facts** otherwise -- lets the system compute real KPIs fully
  offline from the data already pulled by ``sec_fetcher``.

KPI formulas are evaluated in a sandboxed namespace (``__builtins__`` cleared,
only ``abs`` whitelisted).  ``ZeroDivisionError`` / ``NameError`` produce a Note
rather than crashing.
"""

from __future__ import annotations

import logging
import os
import struct
import time
from functools import lru_cache
from typing import Optional

import yaml

from ..config import get_config

logger = logging.getLogger(__name__)

_KPI_YAML = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
                         "config", "kpi.yaml")


@lru_cache(maxsize=1)
def load_kpi_model() -> dict:
    with open(_KPI_YAML, "r", encoding="utf-8") as fh:
        return yaml.safe_load(fh)


# ------------------------------------------------------------------ #
#  Base-metric sources                                               #
# ------------------------------------------------------------------ #
def _facts_from_sec(sec_data: dict) -> dict[str, float]:
    """Map xbrl_tag -> value from a sec_fetcher snapshot."""
    facts: dict[str, float] = {}
    for metric in (sec_data or {}).get("metrics", {}).values():
        tag = metric.get("xbrl_tag")
        val = metric.get("value")
        if tag and val is not None:
            facts[tag] = float(val)
    return facts


def _sql_connection():
    import pyodbc
    from azure.identity import DefaultAzureCredential

    cfg = get_config()
    raw = cfg.azure_sql_conn_string
    if raw and "{" not in raw.replace("{ODBC", "").replace("{SQL", "") and "Pwd=" in raw:
        return pyodbc.connect(raw)
    # Azure AD token auth
    conn_str = raw or (
        f"Driver={{ODBC Driver 18 for SQL Server}};"
        f"Server=tcp:{cfg.azure_sql_server},1433;"
        f"Database={cfg.azure_sql_database};Encrypt=yes;"
    )
    token = DefaultAzureCredential().get_token("https://database.windows.net/.default").token
    enc = token.encode("utf-16-le")
    packed = struct.pack(f"<I{len(enc)}s", len(enc), enc)
    return pyodbc.connect(conn_str, attrs_before={1256: packed})


def _facts_from_sql(cik: str, fy: str, fp: str) -> dict[str, float]:
    query = (
        "SELECT concept, value, unit, period_start, period_end "
        "FROM sec_financial_facts "
        "WHERE cik = ? AND fiscal_year = ? AND fiscal_period = ? AND taxonomy = 'us-gaap' "
        "ORDER BY concept, period_end DESC, period_start DESC, filed_date DESC"
    )
    last_exc: Optional[Exception] = None
    for attempt in range(5):
        try:
            conn = _sql_connection()
            cur = conn.cursor()
            cur.execute(query, (cik, fy, fp))
            facts: dict[str, float] = {}
            for row in cur.fetchall():
                concept = row[0]
                if concept not in facts and row[1] is not None:  # first row per concept
                    facts[concept] = float(row[1])
            conn.close()
            return facts
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            if "40613" in str(exc):  # serverless auto-pause -> wait + retry
                logger.warning("Azure SQL paused, retrying in 20s")
                time.sleep(20)
                continue
            raise
    raise RuntimeError(f"Azure SQL query failed: {last_exc}")


# ------------------------------------------------------------------ #
#  Resolution + computation                                          #
# ------------------------------------------------------------------ #
def _resolve_base_metrics(model: dict, facts: dict[str, float]) -> tuple[dict, list[dict]]:
    values: dict[str, Optional[float]] = {}
    rows: list[dict] = []
    for m in model.get("metrics", []):
        name = m["name"]
        concepts = m.get("concepts") or ([m["concept"]] if m.get("concept") else [])
        value: Optional[float] = None
        matched_concept = None
        for c in concepts:
            if c in facts:
                value = facts[c]
                matched_concept = c
                break
        if value is None and "default" in m:
            value = float(m["default"])
            matched_concept = "(default)"
        values[name] = value
        if value is not None:
            rows.append({"name": name, "concept": matched_concept, "value": value})
    return values, rows


def _fmt(value: float, unit: str) -> str:
    if unit == "pct":
        return f"{value:.2f}%"
    if unit == "ratio":
        return f"{value:.2f}x"
    if unit == "currency":
        return f"${value / 1e9:.2f}B"
    return f"{value:,.2f}"


def _compute_kpis(model: dict, values: dict) -> list[dict]:
    out: list[dict] = []
    eval_ns = {k: v for k, v in values.items() if v is not None}
    for kpi in model.get("kpis", []):
        label = kpi.get("label", kpi["name"])
        unit = kpi.get("unit", "number")
        entry = {"name": kpi["name"], "label": label, "unit": unit,
                 "value": None, "display": None, "note": None}

        missing = [r for r in kpi.get("requires", []) if values.get(r) is None]
        if missing:
            entry["note"] = f"missing input(s): {', '.join(missing)}"
            out.append(entry)
            continue
        try:
            result = eval(str(kpi["formula"]),  # noqa: S307 - sandboxed
                          {"__builtins__": {}, "abs": abs}, eval_ns)
            entry["value"] = round(float(result), 4)
            entry["display"] = _fmt(float(result), unit)
        except ZeroDivisionError:
            entry["note"] = "division by zero"
        except NameError as exc:
            entry["note"] = f"unavailable input ({exc})"
        except Exception as exc:  # noqa: BLE001
            entry["note"] = f"error: {exc}"
        out.append(entry)
    return out


# ------------------------------------------------------------------ #
#  Public API                                                        #
# ------------------------------------------------------------------ #
def run_kpi_analysis(ticker: str, fiscal_year: Optional[str],
                     fiscal_period: Optional[str],
                     sec_data: Optional[dict] = None) -> dict:
    cfg = get_config()
    model = load_kpi_model()

    facts: dict[str, float] = {}
    source = "sec_edgar"
    if cfg.has_sql and sec_data and sec_data.get("cik"):
        try:
            facts = _facts_from_sql(sec_data["cik"], fiscal_year or "", fiscal_period or "")
            source = "azure_sql"
        except Exception as exc:  # noqa: BLE001
            logger.warning("Azure SQL KPI source failed, using SEC facts: %s", exc)
    if not facts:
        facts = _facts_from_sec(sec_data or {})
        source = "sec_edgar"

    values, base_rows = _resolve_base_metrics(model, facts)
    # attach formatted display to base metrics
    for row in base_rows:
        row["display"] = _fmt(row["value"], "currency" if abs(row["value"]) > 1e6 else "number")
    computed = _compute_kpis(model, values)

    return {
        "ticker": ticker.upper(),
        "fiscal_year": fiscal_year,
        "fiscal_period": fiscal_period,
        "model": model.get("model"),
        "model_version": model.get("version"),
        "source": source,
        "base_metrics": base_rows,
        "computed_kpis": computed,
        "_values": values,
    }
