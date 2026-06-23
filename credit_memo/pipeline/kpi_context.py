"""Render KPI data into LLM-ready text artifacts."""

from __future__ import annotations

from typing import Optional


def format_kpi_table(kpi_data: Optional[dict]) -> str:
    if not kpi_data:
        return "KPI TABLE — unavailable."
    ticker = kpi_data.get("ticker", "")
    fy = kpi_data.get("fiscal_year") or ""
    fp = kpi_data.get("fiscal_period") or ""
    model = kpi_data.get("model", "")
    version = kpi_data.get("model_version", "")
    src = kpi_data.get("source", "")

    lines = [f"KPI TABLE — {ticker}  FY{fy} {fp}  (model {model} {version}, source {src})", ""]
    lines.append("Base Metrics:")
    for row in kpi_data.get("base_metrics", []):
        lines.append(f"  {row['name']:<28} {row.get('display', row['value'])}")
    lines.append("")
    lines.append("Computed KPIs:")
    for kpi in kpi_data.get("computed_kpis", []):
        if kpi.get("display") is not None:
            lines.append(f"  {kpi['label']:<28} {kpi['display']}")
        else:
            lines.append(f"  {kpi['label']:<28} N/A ({kpi.get('note')})")
    return "\n".join(lines)


def _kpi(kpi_data: dict, name: str) -> Optional[float]:
    for kpi in kpi_data.get("computed_kpis", []):
        if kpi["name"] == name:
            return kpi.get("value")
    return (kpi_data.get("_values") or {}).get(name)


def build_company_profile_snapshot(kpi_data: Optional[dict]) -> str:
    if not kpi_data:
        return "COMPANY PROFILE SNAPSHOT — unavailable."
    vals = kpi_data.get("_values") or {}
    revenue = vals.get("revenue") or 0
    net_income = vals.get("net_income") or 0
    cash = vals.get("cash_and_equivalents") or 0
    securities = vals.get("marketable_securities") or 0
    ocf = vals.get("operating_cash_flow") or 0
    total_debt = (vals.get("long_term_debt") or 0) + (vals.get("short_term_debt") or 0)
    current_ratio = _kpi(kpi_data, "current_ratio")
    net_margin = _kpi(kpi_data, "net_margin_pct")

    # scale tier
    if revenue >= 100e9:
        scale = "Mega-cap (revenue ≥ $100B)"
    elif revenue >= 10e9:
        scale = "Large-cap ($10B–$100B)"
    elif revenue >= 1e9:
        scale = "Mid-cap ($1B–$10B)"
    else:
        scale = "Small-cap (< $1B)"

    profitability = (f"Profitable ({net_margin:.1f}%)" if (net_margin or 0) > 0
                     else "Unprofitable / break-even")
    liquidity = (
        f"Tight liquidity (current ratio {current_ratio:.2f}x)" if current_ratio and current_ratio < 1
        else f"Adequate liquidity (current ratio {current_ratio:.2f}x)" if current_ratio
        else "Liquidity not computable"
    )
    liquid_assets = cash + securities

    fy = kpi_data.get("fiscal_year") or ""
    fp = kpi_data.get("fiscal_period") or ""
    lines = [
        f"COMPANY PROFILE SNAPSHOT (FY{fy} {fp}):",
        f"- Scale tier        : {scale}",
        f"- Profitability     : {profitability}",
        f"- Liquidity         : {liquidity}",
        "",
        f"Override signals (capacity-relative; total debt = ${total_debt/1e9:.2f}B):",
        f"- Liquid assets ${liquid_assets/1e9:.2f}B vs total debt → "
        f"{'COVERS' if liquid_assets >= total_debt else 'DOES NOT COVER'} (Override Test A)",
        f"- Operating cash flow ${ocf/1e9:.2f}B vs total debt → "
        f"{'COVERS' if ocf >= total_debt else 'DOES NOT COVER'} (Override Test B)",
        f"- Net income ${net_income/1e9:.2f}B vs total debt → "
        f"{'COVERS' if net_income >= total_debt else 'DOES NOT COVER'} (Override Test C)",
    ]
    return "\n".join(lines)
