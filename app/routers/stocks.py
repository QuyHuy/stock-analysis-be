import logging
from fastapi import APIRouter, HTTPException, Header
from ..services import firestore_service
from ..core.firebase import verify_token, get_db

router = APIRouter()
logger = logging.getLogger(__name__)


@router.get("")
async def list_stocks(authorization: str | None = Header(default=None)):
    """Return all stocks in DB, grouped by industry (từ sync / VCI)."""
    verify_token(authorization)
    db = get_db()
    grouped: dict[str, list[dict]] = {}
    symbols: list[str] = []
    try:
        for doc in db.collection("stocks").stream():
            symbol = doc.id
            data = doc.to_dict() or {}
            symbols.append(symbol)
            industry = data.get("industry") or "Khác"
            grouped.setdefault(industry, []).append({
                "symbol": symbol,
                "name": data.get("name") or "",
                "exchange": data.get("exchange") or "",
                "pe": data.get("pe"),
                "market_cap": data.get("market_cap"),
            })
    except Exception as e:
        logger.error("list_stocks failed: %s", e)
        raise
    return {"symbols": symbols, "categories": grouped}


@router.get("/{symbol}")
async def get_stock(symbol: str, authorization: str | None = Header(default=None)):
    verify_token(authorization)
    symbol = symbol.upper()
    info = firestore_service.get_stock_info(symbol)
    if not info:
        raise HTTPException(status_code=404, detail=f"Stock {symbol} not found in database")
    history = firestore_service.get_latest_prices(symbol, limit=90)
    return {"info": info, "history": history}
