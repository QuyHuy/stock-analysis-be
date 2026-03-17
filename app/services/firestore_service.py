import logging
from datetime import datetime, timezone
from google.cloud.firestore_v1.base_query import FieldFilter
from ..core.firebase import get_db

logger = logging.getLogger(__name__)


def upsert_stock(symbol: str, data: dict) -> None:
    try:
        get_db().collection("stocks").document(symbol).set(data, merge=True)
    except Exception as e:
        logger.error("upsert_stock failed for %s: %s", symbol, e)
        raise


def upsert_price_history(symbol: str, date: str, data: dict) -> None:
    try:
        get_db().collection("stocks").document(symbol) \
            .collection("history").document(date).set(data, merge=True)
    except Exception as e:
        logger.error("upsert_price_history failed for %s/%s: %s", symbol, date, e)
        raise


def get_latest_prices(symbol: str, limit: int = 30) -> list[dict]:
    try:
        docs = get_db().collection("stocks").document(symbol) \
            .collection("history") \
            .order_by("date", direction="DESCENDING") \
            .limit(limit) \
            .stream()
        return [doc.to_dict() for doc in docs]
    except Exception as e:
        logger.error("get_latest_prices failed for %s: %s", symbol, e)
        return []


def get_stock_info(symbol: str) -> dict | None:
    try:
        doc = get_db().collection("stocks").document(symbol).get()
        return doc.to_dict() if doc.exists else None
    except Exception as e:
        logger.error("get_stock_info failed for %s: %s", symbol, e)
        return None


def get_active_alerts() -> list[dict]:
    try:
        docs = get_db().collection("alerts") \
            .where(filter=FieldFilter("active", "==", True)) \
            .stream()
        return [{**doc.to_dict(), "id": doc.id} for doc in docs]
    except Exception as e:
        logger.error("get_active_alerts failed: %s", e)
        return []


def deactivate_alert(alert_id: str) -> None:
    try:
        get_db().collection("alerts").document(alert_id).update({"active": False})
    except Exception as e:
        logger.error("deactivate_alert failed for %s: %s", alert_id, e)
        raise


def save_chat_message(uid: str, chat_id: str, role: str, content: str) -> None:
    try:
        get_db().collection("users").document(uid) \
            .collection("chats").document(chat_id) \
            .collection("messages").add({
                "role": role,
                "content": content,
                "createdAt": datetime.now(timezone.utc),
            })
    except Exception as e:
        logger.error("save_chat_message failed for uid=%s: %s", uid, e)
        raise
