import logging
from datetime import datetime, timedelta
from vnstock import Vnstock

logger = logging.getLogger(__name__)

DEFAULT_SYMBOLS = [
    "VNM", "VIC", "VHM", "VCB", "BID", "CTG", "TCB", "MBB", "HPG", "HSG",
    "FPT", "VRE", "MSN", "GAS", "SAB", "PLX", "HDB", "VPB", "ACB", "STB",
    "EIB", "SSI", "VND", "MWG", "PNJ", "DGC", "GEX", "REE", "NLG", "KDH",
    "VCI", "DXG", "BCM", "VGC", "PHR", "CSV", "PDR", "DIG", "CII", "SZC",
    "BWE", "DCM", "DPM", "GVR", "HAH", "HCM", "IDC", "IJC", "IMP", "KBC",
]


def get_stock_price_history(symbol: str, start_date: str, end_date: str) -> list[dict]:
    """Fetch daily OHLCV history for a stock symbol."""
    try:
        stock = Vnstock().stock(symbol=symbol, source="VCI")
        df = stock.quote.history(start=start_date, end=end_date, interval="1D")
        if df is None or df.empty:
            logger.warning("Empty history for %s (%s to %s)", symbol, start_date, end_date)
            return []
        logger.info("Columns for %s: %s", symbol, list(df.columns))
        df = df.reset_index()
        records = []
        for _, row in df.iterrows():
            # Support multiple column naming conventions across vnstock versions
            date_val = (
                row.get("time") or row.get("date") or row.get("Date") or row.get("Time")
            )
            if date_val is None and df.index.name in ("time", "date"):
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


def get_stock_company_info(symbol: str) -> dict:
    """Fetch company overview info for a stock symbol."""
    try:
        stock = Vnstock().stock(symbol=symbol, source="VCI")
        df = stock.company.overview()
        if df is None or df.empty:
            return {"symbol": symbol}
        row = df.iloc[0]
        return {
            "symbol": symbol,
            "name": str(row.get("short_name") or row.get("company_name") or row.get("organ_name") or ""),
            "exchange": str(row.get("exchange") or row.get("stock_exchange") or ""),
            "industry": str(row.get("industry_name") or row.get("icb_name3") or ""),
        }
    except Exception as e:
        logger.warning("Could not fetch company info for %s: %s", symbol, e)
        return {"symbol": symbol}


def get_stock_current_price(symbol: str) -> float | None:
    """Fetch the most recent closing price for a stock."""
    from datetime import timezone
    now = datetime.now(timezone.utc)
    today = now.strftime("%Y-%m-%d")
    week_ago = (now - timedelta(days=7)).strftime("%Y-%m-%d")
    records = get_stock_price_history(symbol, week_ago, today)
    if records:
        return records[-1]["close"]
    return None
