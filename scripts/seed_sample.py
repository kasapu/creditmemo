"""Seed a realistic sample fixture so the pipeline can be exercised without
network access to SEC EDGAR. Useful for offline demos / CI.

Run:  python scripts/seed_sample.py
"""

from __future__ import annotations

from credit_memo.infra import storage


def _m(value, tag, fp="FY", fy=2024, end="2024-09-28"):
    return {"value": value, "value_billions": round(value / 1e9, 4),
            "period_end": end, "fiscal_period": fp, "fiscal_year": fy,
            "form": "10-K", "xbrl_tag": tag}


SAMPLE_AAPL = {
    "cik": "0000320193",
    "ticker": "AAPL",
    "source": "SAMPLE FIXTURE (offline)",
    "metrics": {
        "Revenue": _m(391_035_000_000, "RevenueFromContractWithCustomerExcludingAssessedTax"),
        "CostOfRevenue": _m(210_352_000_000, "CostOfGoodsAndServicesSold"),
        "GrossProfit": _m(180_683_000_000, "GrossProfit"),
        "OperatingIncomeLoss": _m(123_216_000_000, "OperatingIncomeLoss"),
        "NetIncomeLoss": _m(93_736_000_000, "NetIncomeLoss"),
        "InterestExpense": _m(3_750_000_000, "InterestExpense"),
        "Assets": _m(364_980_000_000, "Assets"),
        "AssetsCurrent": _m(152_987_000_000, "AssetsCurrent"),
        "Liabilities": _m(308_030_000_000, "Liabilities"),
        "LiabilitiesCurrent": _m(176_392_000_000, "LiabilitiesCurrent"),
        "StockholdersEquity": _m(56_950_000_000, "StockholdersEquity"),
        "CashAndCashEquivalents": _m(29_943_000_000, "CashAndCashEquivalentsAtCarryingValue"),
        "MarketableSecurities": _m(35_228_000_000, "MarketableSecuritiesCurrent"),
        "AccountsReceivable": _m(33_410_000_000, "AccountsReceivableNetCurrent"),
        "Inventory": _m(7_286_000_000, "InventoryNet"),
        "LongTermDebt": _m(85_750_000_000, "LongTermDebtNoncurrent"),
        "ShortTermDebt": _m(10_912_000_000, "DebtCurrent"),
        "OperatingCashFlow": _m(118_254_000_000, "NetCashProvidedByUsedInOperatingActivities"),
        "CapitalExpenditures": _m(9_447_000_000, "PaymentsToAcquirePropertyPlantAndEquipment"),
    },
    "annual_metrics": {
        "Revenue": [
            {"year": "2022", "val": 394_328_000_000, "value_billions": 394.33, "fiscal_period": "FY"},
            {"year": "2023", "val": 383_285_000_000, "value_billions": 383.29, "fiscal_period": "FY"},
            {"year": "2024", "val": 391_035_000_000, "value_billions": 391.04, "fiscal_period": "FY"},
        ],
    },
    "recent_filings": [
        {"form": "10-K", "date": "2024-11-01", "accession": "0000320193-24-000123",
         "primary_doc": "aapl-20240928.htm"},
    ],
}

# A couple of pre-baked DI chunks so retrieval has something to work with offline.
SAMPLE_CHUNKS = [
    {"id": "AAPL_sample_txt_0", "ticker": "AAPL", "accession": "0000320193-24-000123",
     "form": "10-K", "filing_date": "2024-11-01", "content_type": "text", "page_number": 1,
     "content": "The Company designs, manufactures and markets smartphones, personal "
                "computers, tablets, wearables and accessories, and sells a variety of "
                "related services. Net sales were driven by iPhone, Mac, iPad, Wearables "
                "and Services across the Americas, Europe, Greater China, Japan and Asia."},
    {"id": "AAPL_sample_txt_1", "ticker": "AAPL", "accession": "0000320193-24-000123",
     "form": "10-K", "filing_date": "2024-11-01", "content_type": "text", "page_number": 5,
     "content": "Risk factors include intense competition, macroeconomic conditions, "
                "supply chain concentration, foreign exchange volatility, legal and "
                "regulatory proceedings, and dependence on a limited number of component "
                "suppliers. The Company maintains substantial cash and marketable "
                "securities to manage liquidity risk."},
    {"id": "AAPL_sample_txt_2", "ticker": "AAPL", "accession": "0000320193-24-000123",
     "form": "10-K", "filing_date": "2024-11-01", "content_type": "text", "page_number": 8,
     "content": "Management discussion and analysis: the Company continues to invest in "
                "research and development and expand its Services business. The multi-year "
                "outlook emphasizes installed base growth, margin discipline and capital "
                "return to shareholders through dividends and share repurchases."},
]


def main() -> None:
    storage.save_sec_data("AAPL", SAMPLE_AAPL)
    storage.save_di_chunks("AAPL", SAMPLE_CHUNKS)
    print("Seeded sample fixture for AAPL into", storage.ticker_dir("AAPL"))


if __name__ == "__main__":
    main()
