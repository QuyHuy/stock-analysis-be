from pydantic import BaseModel


class StockInfo(BaseModel):
    symbol: str
    name: str | None = None
    exchange: str | None = None
    sector: str | None = None


class PriceRecord(BaseModel):
    date: str
    open: float
    high: float
    low: float
    close: float
    volume: int
