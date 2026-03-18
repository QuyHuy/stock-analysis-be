import logging
from datetime import datetime, timedelta, timezone
from vnstock import Vnstock

logger = logging.getLogger(__name__)

DEFAULT_SYMBOLS = [
    "VNM", "VIC", "VHM", "VCB", "BID", "CTG", "TCB", "MBB", "HPG", "HSG",
    "FPT", "VRE", "MSN", "GAS", "SAB", "PLX", "HDB", "VPB", "ACB", "STB",
    "EIB", "SSI", "VND", "MWG", "PNJ", "DGC", "GEX", "REE", "NLG", "KDH",
    "VCI", "DXG", "BCM", "VGC", "PHR", "CSV", "PDR", "DIG", "CII", "SZC",
    "BWE", "DCM", "DPM", "GVR", "HAH", "HCM", "IDC", "IJC", "IMP", "KBC",
]


def get_all_symbols() -> list[str]:
    """
    Lấy toàn bộ mã cổ phiếu niêm yết (HOSE, HNX, UPCOM) từ VCI.
    Fallback về DEFAULT_SYMBOLS nếu không gọi được API listing.
    """
    try:
        from vnstock.explorer.vci.listing import Listing
        listing = Listing()
        df = listing.all_symbols()
        if df is not None and not df.empty and "symbol" in df.columns:
            symbols = df["symbol"].astype(str).str.strip().unique().tolist()
            symbols = [s for s in symbols if s and len(s) >= 2]
            if symbols:
                logger.info("Loaded %d symbols from VCI listing", len(symbols))
                return symbols
    except ImportError as e:
        logger.warning("VCI listing not available (%s), using DEFAULT_SYMBOLS", e)
    except Exception as e:
        logger.warning("Failed to fetch all symbols (%s), using DEFAULT_SYMBOLS", e)
    return list(DEFAULT_SYMBOLS)


def _safe_float(val) -> float | None:
    try:
        return round(float(val), 2) if val is not None and val == val else None
    except (TypeError, ValueError):
        return None


def _safe_int(val) -> int | None:
    try:
        return int(float(val)) if val is not None and val == val else None
    except (TypeError, ValueError):
        return None


def _get_row_value(row, *candidates):
    """Lấy giá trị đầu tiên khác None/nan từ row với danh sách tên cột."""
    for col in candidates:
        val = row.get(col) if hasattr(row, "get") else getattr(row, col, None)
        if val is not None and str(val) not in ("nan", "None", ""):
            return val
    return None


def _row_to_dict(row, mapping: dict) -> dict:
    """Extract fields from a DataFrame row using a key mapping."""
    result = {}
    for out_key, candidates in mapping.items():
        cols = candidates if isinstance(candidates, list) else [candidates]
        val = _get_row_value(row, *cols)
        if val is not None:
            result[out_key] = val
    return result


def get_stock_price_history(symbol: str, start_date: str, end_date: str) -> list[dict]:
    """Fetch daily OHLCV history for a stock symbol."""
    try:
        stock = Vnstock().stock(symbol=symbol, source="TCBS")
        df = stock.quote.history(start=start_date, end=end_date, interval="1D")
        if df is None or df.empty:
            logger.warning("Empty history for %s (%s to %s)", symbol, start_date, end_date)
            return []
        df = df.reset_index()
        records = []
        for _, row in df.iterrows():
            date_val = (
                row.get("time") or row.get("date") or row.get("Date") or row.get("Time")
            )
            if date_val is None and hasattr(df, 'index') and df.index.name in ("time", "date"):
                date_val = row.name
            records.append({
                "date": str(date_val)[:10] if date_val is not None else "",
                "open": float(row.get("open") or row.get("Open") or 0),
                "high": float(row.get("high") or row.get("High") or 0),
                "low": float(row.get("low") or row.get("Low") or 0),
                "close": float(row.get("close") or row.get("Close") or 0),
                "volume": int(row.get("volume") or row.get("Volume") or 0),
            })
        return [r for r in records if r["date"]]
    except Exception as e:
        logger.error("Error fetching price history for %s: %s", symbol, e)
        return []


def get_stock_fundamentals(symbol: str) -> dict:
    """
    Fetch comprehensive fundamental data:
    - Company overview (name, exchange, industry)
    - Financial ratios (PE, PB, ROE, ROA, EPS, margins, growth)
    - Income statement (last 8 quarters: revenue, gross profit, net profit, EBIT)
    - Balance sheet (last 4 quarters: assets, liabilities, equity, debt)
    - Cash flow (last 4 quarters: operating, investing, financing)
    """
    result: dict = {"symbol": symbol}
    try:
        stock = Vnstock().stock(symbol=symbol, source="TCBS")

        # ── Company overview ──────────────────────────────────────────────────
        try:
            df = stock.company.overview()
            if df is not None and not df.empty:
                row = df.iloc[0]
                result["name"] = str(
                    _get_row_value(row, "short_name", "company_name", "organ_name") or ""
                )
                result["exchange"] = str(
                    _get_row_value(row, "exchange", "stock_exchange", "com_group_code") or ""
                )
                result["industry"] = str(
                    _get_row_value(row, "industry_name", "icb_name3", "industry") or ""
                )
                market_cap = _get_row_value(
                    row,
                    "market_cap", "marketCap", "market_cap_vnd", "capitalization",
                    "von_hoa", "total_value",
                )
                result["market_cap"] = _safe_float(market_cap)
                # Fallback: ước tính vốn hóa từ giá * KL niêm yết (nếu có)
                if result.get("market_cap") is None:
                    outstanding = _get_row_value(row, "outstanding_share", "outstandingShare", "listing_volume", "kl_niem_yet")
                    if outstanding is not None:
                        try:
                            price = _get_row_value(row, "price", "close", "last_price")
                            if price is not None:
                                result["market_cap"] = _safe_float(float(price) * float(outstanding))
                        except (TypeError, ValueError):
                            pass
            else:
                logger.debug("Overview empty for %s", symbol)
        except Exception as e:
            logger.warning("Overview failed %s: %s", symbol, e)

        # ── Financial ratios (latest quarter) ────────────────────────────────
        try:
            rdf = stock.finance.ratio(period="quarter", lang="en")
            if rdf is not None and not rdf.empty:
                r = rdf.iloc[0]
                result["pe"] = _safe_float(_get_row_value(
                    r, "priceToEarning", "pe", "price_to_earning", "p_e", "P/E"
                ))
                result["pb"] = _safe_float(_get_row_value(
                    r, "priceToBook", "pb", "price_to_book", "p_b", "P/B"
                ))
                result["ps"] = _safe_float(_get_row_value(
                    r, "priceToSale", "ps", "price_to_sale", "p_s", "P/S"
                ))
                result["roe"] = _safe_float(_get_row_value(
                    r, "returnOnEquity", "roe", "ROE", "return_on_equity"
                ))
                result["roa"] = _safe_float(_get_row_value(
                    r, "returnOnAsset", "roa", "ROA", "return_on_asset"
                ))
                result["eps"] = _safe_float(_get_row_value(
                    r, "earningPerShare", "eps", "earning_per_share", "EPS"
                ))
                result["bvps"] = _safe_float(_get_row_value(
                    r, "bookValuePerShare", "bvps", "book_value_per_share", "BVPS"
                ))
                result["gross_margin"] = _safe_float(_get_row_value(
                    r, "grossProfitMargin", "grossMargin", "gross_margin", "gross_profit_margin"
                ))
                result["net_margin"] = _safe_float(_get_row_value(
                    r, "netProfitMargin", "netMargin", "net_margin", "postTaxMargin", "net_profit_margin"
                ))
                result["revenue_growth"] = _safe_float(_get_row_value(
                    r, "revenueGrowth", "revenue_growth", "epsChange"
                ))
                result["profit_growth"] = _safe_float(_get_row_value(
                    r, "profitGrowth", "earningGrowth", "profit_growth", "earning_growth"
                ))
                result["debt_equity"] = _safe_float(_get_row_value(
                    r, "debtToEquity", "debtOnEquity", "debt_equity", "debt_on_equity"
                ))
                result["current_ratio"] = _safe_float(_get_row_value(
                    r, "currentRatio", "currentPayment", "current_ratio", "quickPayment"
                ))
                result["dividend_yield"] = _safe_float(_get_row_value(
                    r, "dividendYield", "dividend", "dividend_yield"
                ))
            else:
                logger.debug("Ratio empty for %s", symbol)
        except Exception as e:
            logger.warning("Ratios failed %s: %s", symbol, e)

        # ── Income statement (last 8 quarters) ───────────────────────────────
        try:
            idf = stock.finance.income_statement(period="quarter", lang="en")
            if idf is not None and not idf.empty:
                quarters = []
                for _, row in idf.head(8).iterrows():
                    q = _row_to_dict(row, {
                        "period":          ["quarter", "yearReport", "lengthReport", "year"],
                        "revenue":         ["revenue", "netRevenue", "net_revenue"],
                        "gross_profit":    ["grossProfit", "gross_profit"],
                        "operating_profit":["operatingProfit", "ebit", "operating_profit"],
                        "net_profit":      ["netProfit", "net_profit", "profitAfterTax"],
                        "ebitda":          ["ebitda"],
                        "interest_expense":["interestExpense", "interest_expense"],
                    })
                    # Convert to billions VND for readability
                    for k in ("revenue", "gross_profit", "operating_profit", "net_profit", "ebitda"):
                        if k in q and q[k] is not None:
                            q[k] = _safe_float(float(q[k]) / 1e9)
                    if q:
                        quarters.append(q)
                result["income_quarters"] = quarters
        except Exception as e:
            logger.warning("Income statement failed %s: %s", symbol, e)

        # ── Balance sheet (last 4 quarters) ──────────────────────────────────
        try:
            bdf = stock.finance.balance_sheet(period="quarter", lang="en")
            if bdf is not None and not bdf.empty:
                quarters = []
                for _, row in bdf.head(4).iterrows():
                    q = _row_to_dict(row, {
                        "period":          ["quarter", "yearReport", "year"],
                        "total_assets":    ["asset", "totalAsset", "total_asset"],
                        "total_liabilities":["debt", "totalDebt", "liability", "totalLiability"],
                        "equity":          ["equity", "ownerEquity", "owner_equity"],
                        "short_term_debt": ["shortDebt", "short_term_debt"],
                        "long_term_debt":  ["longDebt", "long_term_debt"],
                        "cash":            ["cash", "cashAndCashEquivalents"],
                        "inventory":       ["inventory"],
                        "receivables":     ["receivables", "shortReceivable"],
                    })
                    for k in ("total_assets", "total_liabilities", "equity",
                              "short_term_debt", "long_term_debt", "cash"):
                        if k in q and q[k] is not None:
                            q[k] = _safe_float(float(q[k]) / 1e9)
                    if q:
                        quarters.append(q)
                result["balance_quarters"] = quarters
        except Exception as e:
            logger.warning("Balance sheet failed %s: %s", symbol, e)

        # ── Cash flow (last 4 quarters) ───────────────────────────────────────
        try:
            cdf = stock.finance.cash_flow(period="quarter", lang="en")
            if cdf is not None and not cdf.empty:
                quarters = []
                for _, row in cdf.head(4).iterrows():
                    q = _row_to_dict(row, {
                        "period":         ["quarter", "yearReport", "year"],
                        "operating_cf":   ["operatingCashFlow", "operating_cash_flow", "cashFromOperating"],
                        "investing_cf":   ["investingCashFlow", "investing_cash_flow", "cashFromInvesting"],
                        "financing_cf":   ["financingCashFlow", "financing_cash_flow", "cashFromFinancing"],
                        "capex":          ["capex", "purchaseFixedAsset"],
                        "free_cash_flow": ["freeCashFlow", "free_cash_flow"],
                    })
                    for k in ("operating_cf", "investing_cf", "financing_cf", "capex", "free_cash_flow"):
                        if k in q and q[k] is not None:
                            q[k] = _safe_float(float(q[k]) / 1e9)
                    if q:
                        quarters.append(q)
                result["cashflow_quarters"] = quarters
        except Exception as e:
            logger.warning("Cash flow failed %s: %s", symbol, e)

    except Exception as e:
        logger.warning("Could not fetch fundamentals for %s: %s", symbol, e)

    return result


def get_stock_current_price(symbol: str) -> float | None:
    """Fetch the most recent closing price for a stock."""
    now = datetime.now(timezone.utc)
    today = now.strftime("%Y-%m-%d")
    week_ago = (now - timedelta(days=7)).strftime("%Y-%m-%d")
    records = get_stock_price_history(symbol, week_ago, today)
    if records:
        return records[-1]["close"]
    return None
