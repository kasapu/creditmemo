"""SEC EDGAR data fetcher.

Pure ``urllib`` based client for the public SEC EDGAR REST API.  No SDK and no
credentials are required -- only a descriptive ``User-Agent`` header (SEC fair
access policy).  This module powers the system in offline / mock mode because
it provides genuine financial data.
"""

from __future__ import annotations

import json
import logging
import time
import urllib.request
from typing import Any, Optional

from ..config import get_config

logger = logging.getLogger(__name__)

SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik}.json"
COMPANYCONCEPT_URL = (
    "https://data.sec.gov/api/xbrl/companyconcept/CIK{cik}/us-gaap/{tag}.json"
)
TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
ARCHIVE_DOC_URL = "https://www.sec.gov/Archives/edgar/data/{cik}/{acc}/{doc}"

# ------------------------------------------------------------------ #
#  XBRL concept waterfalls (sector aware -- first match wins)         #
# ------------------------------------------------------------------ #
REVENUE_TAGS = [
    "RevenueFromContractWithCustomerExcludingAssessedTax",
    "Revenues",
    "SalesRevenueNet",
    "RevenueFromContractWithCustomerIncludingAssessedTax",
    "RevenuesNetOfInterestExpense",
    "InterestAndDividendIncomeOperating",
]

# Concepts pulled for the latest period + 3-year annual series. The first
# entry of each waterfall that returns data is used.
CONCEPT_WATERFALLS: dict[str, list[str]] = {
    "Revenue": REVENUE_TAGS,
    "CostOfRevenue": ["CostOfRevenue", "CostOfGoodsAndServicesSold", "CostOfGoodsSold"],
    "GrossProfit": ["GrossProfit"],
    "OperatingIncomeLoss": ["OperatingIncomeLoss"],
    "NetIncomeLoss": ["NetIncomeLoss", "ProfitLoss"],
    "Assets": ["Assets"],
    "AssetsCurrent": ["AssetsCurrent"],
    "Liabilities": ["Liabilities"],
    "LiabilitiesCurrent": ["LiabilitiesCurrent"],
    "StockholdersEquity": [
        "StockholdersEquity",
        "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest",
    ],
    "CashAndCashEquivalents": [
        "CashAndCashEquivalentsAtCarryingValue",
        "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents",
    ],
    "MarketableSecurities": [
        "MarketableSecuritiesCurrent",
        "ShortTermInvestments",
        "AvailableForSaleSecuritiesDebtSecuritiesCurrent",
    ],
    "AccountsReceivable": [
        "AccountsReceivableNetCurrent",
        "ReceivablesNetCurrent",
    ],
    "Inventory": ["InventoryNet"],
    "LongTermDebt": ["LongTermDebtNoncurrent", "LongTermDebt", "LongTermDebtAndCapitalLeaseObligations"],
    "ShortTermDebt": ["DebtCurrent", "ShortTermBorrowings", "LongTermDebtCurrent"],
    "InterestExpense": ["InterestExpense", "InterestExpenseDebt"],
    "OperatingCashFlow": [
        "NetCashProvidedByUsedInOperatingActivities",
        "NetCashProvidedByUsedInOperatingActivitiesContinuingOperations",
    ],
    "CapitalExpenditures": [
        "PaymentsToAcquirePropertyPlantAndEquipment",
        "PaymentsToAcquireProductiveAssets",
    ],
}


# ------------------------------------------------------------------ #
#  Low level HTTP helpers                                            #
# ------------------------------------------------------------------ #
def _request(url: str, *, expect_json: bool = True, retries: int = 3) -> Any:
    cfg = get_config()
    headers = {
        "User-Agent": cfg.sec_user_agent,
        "Accept-Encoding": "gzip, deflate",
    }
    last_exc: Optional[Exception] = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=30) as resp:
                raw = resp.read()
                if resp.headers.get("Content-Encoding") == "gzip":
                    import gzip
                    raw = gzip.decompress(raw)
                if expect_json:
                    return json.loads(raw.decode("utf-8"))
                return raw.decode("utf-8", errors="replace")
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            wait = 2 ** attempt
            logger.warning("SEC request failed (%s/%s) %s: %s -- retry in %ss",
                           attempt + 1, retries, url, exc, wait)
            time.sleep(wait)
    raise RuntimeError(f"SEC request failed after {retries} attempts: {url}") from last_exc


# ------------------------------------------------------------------ #
#  CIK + filings                                                     #
# ------------------------------------------------------------------ #
def resolve_cik(ticker: str) -> str:
    """Return the 10-digit zero-padded CIK for a ticker."""
    ticker = ticker.strip().upper()
    data = _request(TICKERS_URL)
    for entry in data.values():
        if entry.get("ticker", "").upper() == ticker:
            return str(entry["cik_str"]).zfill(10)
    raise ValueError(f"Ticker not found on SEC EDGAR: {ticker}")


def get_recent_filings(cik: str, forms: Optional[set[str]] = None,
                       limit: int = 40) -> list[dict]:
    """Return recent filings (most recent first)."""
    data = _request(SUBMISSIONS_URL.format(cik=cik))
    recent = data.get("filings", {}).get("recent", {})
    forms_list = recent.get("form", [])
    dates = recent.get("filingDate", [])
    accessions = recent.get("accessionNumber", [])
    primary_docs = recent.get("primaryDocument", [])
    out: list[dict] = []
    for i in range(len(forms_list)):
        form = forms_list[i]
        if forms and form not in forms:
            continue
        out.append({
            "form": form,
            "date": dates[i] if i < len(dates) else None,
            "accession": accessions[i] if i < len(accessions) else None,
            "primary_doc": primary_docs[i] if i < len(primary_docs) else None,
        })
        if len(out) >= limit:
            break
    return out


def get_latest_10k_10q(cik: str) -> list[dict]:
    """Return the latest 10-K and latest 10-Q (whichever exist)."""
    filings = get_recent_filings(cik, forms={"10-K", "10-Q"}, limit=40)
    out: list[dict] = []
    for wanted in ("10-K", "10-Q"):
        for f in filings:
            if f["form"] == wanted:
                out.append(f)
                break
    return out


def filing_doc_url(cik: str, accession: str, primary_doc: str) -> str:
    acc_clean = accession.replace("-", "")
    cik_int = str(int(cik))  # strip leading zeros for archive path
    return ARCHIVE_DOC_URL.format(cik=cik_int, acc=acc_clean, doc=primary_doc)


# ------------------------------------------------------------------ #
#  XBRL facts                                                        #
# ------------------------------------------------------------------ #
def _concept_facts(cik: str, tag: str) -> Optional[dict]:
    url = COMPANYCONCEPT_URL.format(cik=cik, tag=tag)
    try:
        return _request(url)
    except Exception:
        return None


def _latest_fact(cik: str, tags: list[str]) -> Optional[dict]:
    """Latest USD value across a waterfall of tags. Returns a fact dict."""
    for tag in tags:
        data = _concept_facts(cik, tag)
        if not data:
            continue
        units = data.get("units", {})
        facts = units.get("USD") or units.get("USD/shares") or next(iter(units.values()), [])
        if not facts:
            continue
        # most recent by end date / filed
        facts_sorted = sorted(
            facts,
            key=lambda f: (f.get("end", ""), f.get("filed", "")),
            reverse=True,
        )
        latest = facts_sorted[0]
        return {
            "value": latest.get("val"),
            "value_billions": round(latest.get("val", 0) / 1e9, 4),
            "period_start": latest.get("start"),
            "period_end": latest.get("end"),
            "fiscal_period": latest.get("fp"),
            "fiscal_year": latest.get("fy"),
            "form": latest.get("form"),
            "xbrl_tag": tag,
        }
    return None


def _annual_series(cik: str, tags: list[str], years: int = 3) -> list[dict]:
    """Last *years* annual (10-K, FY) values for a concept waterfall."""
    for tag in tags:
        data = _concept_facts(cik, tag)
        if not data:
            continue
        units = data.get("units", {})
        facts = units.get("USD") or next(iter(units.values()), [])
        annual = [f for f in facts if f.get("form") == "10-K" and f.get("fp") == "FY" and f.get("fy")]
        # de-dupe by fiscal year (keep latest filed)
        by_year: dict[int, dict] = {}
        for f in annual:
            fy = f.get("fy")
            if fy not in by_year or f.get("filed", "") > by_year[fy].get("filed", ""):
                by_year[fy] = f
        rows = [
            {
                "year": str(fy),
                "val": f.get("val"),
                "value_billions": round(f.get("val", 0) / 1e9, 4),
                "fiscal_period": "FY",
            }
            for fy, f in sorted(by_year.items())
        ]
        if rows:
            return rows[-years:]
    return []


# ------------------------------------------------------------------ #
#  Orchestrator                                                      #
# ------------------------------------------------------------------ #
def get_quarterly_financials(ticker: str) -> dict:
    """Pull the full financial snapshot for a ticker from SEC EDGAR."""
    cik = resolve_cik(ticker)
    metrics: dict[str, dict] = {}
    annual_metrics: dict[str, list[dict]] = {}

    for name, tags in CONCEPT_WATERFALLS.items():
        fact = _latest_fact(cik, tags)
        if fact:
            metrics[name] = fact
        series = _annual_series(cik, tags)
        if series:
            annual_metrics[name] = series

    recent_filings = get_recent_filings(cik, forms={"10-K", "10-Q"}, limit=10)

    return {
        "cik": cik,
        "ticker": ticker.upper(),
        "source": "SEC EDGAR",
        "metrics": metrics,
        "annual_metrics": annual_metrics,
        "recent_filings": recent_filings,
    }


# ------------------------------------------------------------------ #
#  HTML -> text                                                      #
# ------------------------------------------------------------------ #
def fetch_filing_html(cik: str, accession: str, primary_doc: str) -> str:
    url = filing_doc_url(cik, accession, primary_doc)
    return _request(url, expect_json=False)


def html_to_text(html: str) -> str:
    """Strip XBRL/HTML to clean plain text."""
    try:
        from bs4 import BeautifulSoup
    except Exception:  # pragma: no cover
        # crude fallback if bs4 missing
        import re
        text = re.sub(r"<[^>]+>", " ", html)
        return re.sub(r"\s+", " ", text).strip()

    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style"]):
        tag.decompose()
    text = soup.get_text(separator="\n")
    lines = [ln.strip() for ln in text.splitlines()]
    return "\n".join(ln for ln in lines if ln)
