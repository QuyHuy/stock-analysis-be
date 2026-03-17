import logging
from fastapi import APIRouter, HTTPException, Header
from ..services import firestore_service
from ..services.vnstock_service import DEFAULT_SYMBOLS
from ..core.firebase import verify_token, get_db

router = APIRouter()
logger = logging.getLogger(__name__)


@router.get("")
async def list_stocks(authorization: str | None = Header(default=None)):
    """Return all tracked symbols grouped by industry."""
    verify_token(authorization)
    db = get_db()
    grouped: dict[str, list[dict]] = {}
    for symbol in DEFAULT_SYMBOLS:
        try:
            doc = db.collection("stocks").document(symbol).get()
            data = doc.to_dict() if doc.exists else {}
        except Exception:
            data = {}
        industry = data.get("industry") or "Khác"
        name = data.get("name") or ""
        exchange = data.get("exchange") or ""
        pe = data.get("pe")
        grouped.setdefault(industry, []).append({
            "symbol": symbol,
            "name": name,
            "exchange": exchange,
            "pe": pe,
        })
    return {"symbols": DEFAULT_SYMBOLS, "categories": grouped}


@router.get("/{symbol}")
async def get_stock(symbol: str, authorization: str | None = Header(default=None)):
    verify_token(authorization)
    symbol = symbol.upper()
    info = firestore_service.get_stock_info(symbol)
    if not info:
        raise HTTPException(status_code=404, detail=f"Stock {symbol} not found in database")
    history = firestore_service.get_latest_prices(symbol, limit=90)
    return {"info": info, "history": history}
