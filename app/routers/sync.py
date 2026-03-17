import logging
from datetime import datetime, timedelta
from fastapi import APIRouter, BackgroundTasks

from ..services.vnstock_service import get_stock_price_history, DEFAULT_SYMBOLS
from ..services.firestore_service import upsert_stock, upsert_price_history

router = APIRouter()
logger = logging.getLogger(__name__)


async def _sync_stocks() -> None:
    """Sync 90 days of price history for all DEFAULT_SYMBOLS into Firestore."""
    end_date = datetime.now().strftime("%Y-%m-%d")
    start_date = (datetime.now() - timedelta(days=90)).strftime("%Y-%m-%d")
    success_count = 0

    for symbol in DEFAULT_SYMBOLS:
        try:
            upsert_stock(symbol, {"symbol": symbol, "updatedAt": datetime.now()})
            records = get_stock_price_history(symbol, start_date, end_date)
            for record in records:
                upsert_price_history(symbol, record["date"], record)
            success_count += 1
            logger.info("Synced %s: %d records", symbol, len(records))
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
