import logging
from fastapi import APIRouter, HTTPException, Header
from ..services import firestore_service
from ..services.vnstock_service import DEFAULT_SYMBOLS
from ..core.firebase import verify_token

router = APIRouter()
logger = logging.getLogger(__name__)


@router.get("")
async def list_stocks(authorization: str | None = Header(default=None)):
    verify_token(authorization)
    return {"symbols": DEFAULT_SYMBOLS}


@router.get("/{symbol}")
async def get_stock(symbol: str, authorization: str | None = Header(default=None)):
    verify_token(authorization)
    symbol = symbol.upper()
    info = firestore_service.get_stock_info(symbol)
    if not info:
        raise HTTPException(status_code=404, detail=f"Stock {symbol} not found in database")
    history = firestore_service.get_latest_prices(symbol, limit=90)
    return {"info": info, "history": history}
