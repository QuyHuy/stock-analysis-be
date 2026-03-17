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
        df = stock.quote().history(start=start_date, end=end_date, interval="1D")
        if df is None or df.empty:
            return []
        records = []
        for _, row in df.iterrows():
            records.append({
                "date": str(row.get("time", row.name))[:10],
                "open": float(row.get("open", 0)),
                "high": float(row.get("high", 0)),
                "low": float(row.get("low", 0)),
                "close": float(row.get("close", 0)),
                "volume": int(row.get("volume", 0)),
            })
        return records
    except Exception as e:
        logger.error("Error fetching price history for %s: %s", symbol, e)
        return []


def get_stock_current_price(symbol: str) -> float | None:
    """Fetch the most recent closing price for a stock."""
    today = datetime.now().strftime("%Y-%m-%d")
    week_ago = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
    records = get_stock_price_history(symbol, week_ago, today)
    if records:
        return records[-1]["close"]
    return None
