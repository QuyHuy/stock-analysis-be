from pydantic import BaseModel
from typing import Literal


class AlertCreate(BaseModel):
    symbol: str
    condition: Literal["above", "below"]
    price: float


class Alert(AlertCreate):
    id: str
    uid: str
    active: bool = True
