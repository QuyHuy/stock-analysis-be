import logging
from datetime import datetime
from google.cloud.firestore_v1.base_query import FieldFilter
from ..core.firebase import get_db

logger = logging.getLogger(__name__)


def upsert_stock(symbol: str, data: dict) -> None:
    get_db().collection("stocks").document(symbol).set(data, merge=True)


def upsert_price_history(symbol: str, date: str, data: dict) -> None:
    get_db().collection("stocks").document(symbol) \
        .collection("history").document(date).set(data, merge=True)


def get_latest_prices(symbol: str, limit: int = 30) -> list[dict]:
    docs = get_db().collection("stocks").document(symbol) \
        .collection("history") \
        .order_by("date", direction="DESCENDING") \
        .limit(limit) \
        .stream()
    return [doc.to_dict() for doc in docs]


def get_stock_info(symbol: str) -> dict | None:
    doc = get_db().collection("stocks").document(symbol).get()
    return doc.to_dict() if doc.exists else None


def get_active_alerts() -> list[dict]:
    docs = get_db().collection("alerts") \
        .where(filter=FieldFilter("active", "==", True)) \
        .stream()
    return [{**doc.to_dict(), "id": doc.id} for doc in docs]


def deactivate_alert(alert_id: str) -> None:
    get_db().collection("alerts").document(alert_id).update({"active": False})


def save_chat_message(uid: str, chat_id: str, role: str, content: str) -> None:
    get_db().collection("users").document(uid) \
        .collection("chats").document(chat_id) \
        .collection("messages").add({
            "role": role,
            "content": content,
            "createdAt": datetime.now(),
        })
