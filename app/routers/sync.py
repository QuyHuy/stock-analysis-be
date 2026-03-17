import asyncio
import logging
from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, BackgroundTasks

from ..services.vnstock_service import get_stock_price_history, get_stock_fundamentals, DEFAULT_SYMBOLS
from ..services.firestore_service import upsert_stock, upsert_price_history

router = APIRouter()
logger = logging.getLogger(__name__)


def _sync_one_symbol(symbol: str, start_date: str, end_date: str) -> int:
    """Sync price history + full fundamental data for one symbol."""
    # Fetch fundamentals (overview + ratios + income + balance + cashflow)
    fundamentals = get_stock_fundamentals(symbol)
    fundamentals["updatedAt"] = datetime.now(timezone.utc)
    upsert_stock(symbol, fundamentals)

    # Fetch price history
    records = get_stock_price_history(symbol, start_date, end_date)
    for record in records:
        upsert_price_history(symbol, record["date"], record)
    return len(records)


async def _sync_stocks() -> None:
    """Sync 90 days of price history for all DEFAULT_SYMBOLS into Firestore.

    Each symbol is synced in a thread pool to avoid blocking the event loop
    with synchronous vnstock HTTP calls and Firestore writes.
    """
    end_date = datetime.now().strftime("%Y-%m-%d")
    start_date = (datetime.now() - timedelta(days=200)).strftime("%Y-%m-%d")
    success_count = 0

    for symbol in DEFAULT_SYMBOLS:
        try:
            count = await asyncio.to_thread(_sync_one_symbol, symbol, start_date, end_date)
            success_count += 1
            logger.info("Synced %s: %d records", symbol, count)
        except Exception as e:
            logger.error("Failed to sync %s: %s", symbol, e)

    logger.info("Sync complete: %d/%d stocks", success_count, len(DEFAULT_SYMBOLS))


@router.post("")
async def trigger_sync(background_tasks: BackgroundTasks):
    """
    Trigger a full data sync from vnstock into Firestore.
    Called by Cloud Scheduler daily at 18:00 VN time, or manually by admin.
    """
    background_tasks.add_task(_sync_stocks)
    return {"message": "Sync started", "timestamp": datetime.now().isoformat()}
