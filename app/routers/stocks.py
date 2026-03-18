import asyncio
import logging
from fastapi import APIRouter, HTTPException, Header
from ..services import firestore_service
from ..services.stock_signals_service import (
    compute_signals,
    fetch_kbs_live_row,
    tradingview_symbol,
    normalize_exchange,
    _EX_ORDER,
)
from ..core.firebase import verify_token, get_db

router = APIRouter()
logger = logging.getLogger(__name__)


def _ex_sort_key(ex: str) -> int:
    try:
        return _EX_ORDER.index(ex.upper())
    except ValueError:
        return 99


@router.get("")
async def list_stocks(authorization: str | None = Header(default=None)):
    """
    Toàn bộ cổ phiếu trong DB, nhóm theo Sàn + Ngành (category hợp lý).
    """
    verify_token(authorization)
    db = get_db()
    categories_industry: dict[str, list[dict]] = {}
    by_ex_ind: dict[str, dict[str, list[dict]]] = {}
    symbols: list[str] = []

    try:
        for doc in db.collection("stocks").stream():
            symbol = doc.id
            data = doc.to_dict() or {}
            symbols.append(symbol)
            ex = normalize_exchange(data.get("exchange"))
            industry = (data.get("industry") or "Khác").strip() or "Khác"
            item = {
                "symbol": symbol,
                "name": data.get("name") or "",
                "exchange": ex,
                "pe": data.get("pe"),
                "market_cap": data.get("market_cap"),
                "industry": industry,
            }
            categories_industry.setdefault(industry, []).append(item)
            by_ex_ind.setdefault(ex, {}).setdefault(industry, []).append(item)
    except Exception as e:
        logger.error("list_stocks failed: %s", e)
        raise

    groups: list[dict] = []
    for ex in sorted(by_ex_ind.keys(), key=_ex_sort_key):
        for ind in sorted(by_ex_ind[ex].keys(), key=lambda x: (-len(by_ex_ind[ex][x]), x)):
            stocks = sorted(by_ex_ind[ex][ind], key=lambda x: x["symbol"])
            groups.append({
                "id": f"{ex}|{ind}",
                "exchange": ex,
                "industry": ind,
                "title": f"{ex} · {ind}",
                "count": len(stocks),
                "stocks": stocks,
            })

    return {
        "symbols": sorted(set(symbols)),
        "total": len(symbols),
        "groups": groups,
        "categories": categories_industry,
    }


@router.get("/{symbol}")
async def get_stock(symbol: str, authorization: str | None = Header(default=None)):
    verify_token(authorization)
    symbol = symbol.upper()
    info = firestore_service.get_stock_info(symbol)
    if not info:
        raise HTTPException(status_code=404, detail=f"Stock {symbol} not found in database")
    history = firestore_service.get_latest_prices(symbol, limit=100)

    live_task = asyncio.to_thread(fetch_kbs_live_row, symbol, info.get("exchange"))
    live_quote = await live_task
    signals = compute_signals(history, info)
    tv = tradingview_symbol(symbol, info.get("exchange"))

    return {
        "info": info,
        "history": history,
        "live_quote": live_quote,
        "signals": signals,
        "tradingview_symbol": tv,
    }
