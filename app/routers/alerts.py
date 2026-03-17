import asyncio
import logging
from datetime import datetime, timezone
from fastapi import APIRouter, BackgroundTasks, Header, HTTPException
from google.cloud.firestore_v1.base_query import FieldFilter

from ..models.alert import Alert, AlertCreate
from ..services import firestore_service, telegram_service
from ..services.vnstock_service import get_stock_current_price
from ..core import firebase
from ..core.firebase import verify_token

router = APIRouter()
logger = logging.getLogger(__name__)


@router.post("", response_model=Alert)
async def create_alert(
    alert: AlertCreate,
    authorization: str | None = Header(default=None),
):
    uid = verify_token(authorization)
    db = firebase.get_db()
    doc_ref = db.collection("alerts").document()
    data = {
        **alert.model_dump(),
        "uid": uid,
        "active": True,
        "createdAt": datetime.now(timezone.utc),
    }
    doc_ref.set(data)
    return Alert(id=doc_ref.id, uid=uid, **alert.model_dump())


@router.get("", response_model=list[Alert])
async def list_alerts(authorization: str | None = Header(default=None)):
    uid = verify_token(authorization)
    db = firebase.get_db()
    docs = (
        db.collection("alerts")
        .where(filter=FieldFilter("uid", "==", uid))
        .where(filter=FieldFilter("active", "==", True))
        .stream()
    )
    return [Alert(id=doc.id, **doc.to_dict()) for doc in docs]


@router.delete("/{alert_id}", status_code=204)
async def delete_alert(
    alert_id: str,
    authorization: str | None = Header(default=None),
):
    verify_token(authorization)
    firestore_service.deactivate_alert(alert_id)


@router.post("/check")
async def check_alerts(background_tasks: BackgroundTasks):
    """Called by Cloud Scheduler every 15 min during trading hours (09:00–14:45 VN)."""
    background_tasks.add_task(_check_and_notify)
    return {"message": "Alert check started"}


async def _check_and_notify() -> None:
    alerts = firestore_service.get_active_alerts()
    db = firebase.get_db()
    for alert in alerts:
        current_price = await asyncio.to_thread(get_stock_current_price, alert["symbol"])
        if current_price is None:
            continue
        triggered = (
            alert["condition"] == "above" and current_price >= alert["price"]
        ) or (
            alert["condition"] == "below" and current_price <= alert["price"]
        )
        if not triggered:
            continue
        user_doc = db.collection("users").document(alert["uid"]).get()
        if user_doc.exists:
            telegram_id = user_doc.to_dict().get("telegramChatId")
            if telegram_id:
                await telegram_service.send_alert_message(
                    telegram_id, alert["symbol"], current_price, alert["condition"]
                )
        firestore_service.deactivate_alert(alert["id"])
        logger.info("Alert triggered: %s %s %.1f", alert["symbol"], alert["condition"], current_price)
