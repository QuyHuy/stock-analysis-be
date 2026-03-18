import asyncio
import logging
from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, BackgroundTasks

from ..services.vnstock_service import (
    get_stock_price_history,
    get_stock_fundamentals,
    get_all_symbols,
    DEFAULT_SYMBOLS,
)
from ..services.firestore_service import upsert_stock, upsert_price_history

router = APIRouter()
logger = logging.getLogger(__name__)


def _sync_one_symbol(symbol: str, start_date: str, end_date: str) -> int:
    """Sync price history + full fundamental data for one symbol."""
    fundamentals = get_stock_fundamentals(symbol)
    fundamentals["updatedAt"] = datetime.now(timezone.utc)
    upsert_stock(symbol, fundamentals)

    records = get_stock_price_history(symbol, start_date, end_date)
    for record in records:
        upsert_price_history(symbol, record["date"], record)
    return len(records)


async def _sync_stocks(full_market: bool = True) -> None:
    """Sync price history + fundamentals into Firestore.

    full_market=True: lấy toàn bộ mã từ VCI (get_all_symbols).
    full_market=False: chỉ sync DEFAULT_SYMBOLS (nhanh hơn).
    """
    end_date = datetime.now().strftime("%Y-%m-%d")
    start_date = (datetime.now() - timedelta(days=200)).strftime("%Y-%m-%d")

    symbols = get_all_symbols() if full_market else list(DEFAULT_SYMBOLS)
    success_count = 0

    for symbol in symbols:
        try:
            count = await asyncio.to_thread(_sync_one_symbol, symbol, start_date, end_date)
            success_count += 1
            logger.info("Synced %s: %d records", symbol, count)
        except Exception as e:
            logger.error("Failed to sync %s: %s", symbol, e)

    logger.info("Sync complete: %d/%d stocks", success_count, len(symbols))


@router.post("")
async def trigger_sync(
    background_tasks: BackgroundTasks,
    full_market: bool = True,
):
    """
    Trigger data sync from vnstock into Firestore.
    full_market=True (default): sync toàn bộ mã từ VCI.
    full_market=False: chỉ sync danh sách mặc định (nhanh hơn).
    """
    background_tasks.add_task(_sync_stocks, full_market)
    return {
        "message": "Sync started",
        "full_market": full_market,
        "timestamp": datetime.now().isoformat(),
    }
