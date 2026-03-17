import logging
import httpx
from ..core.config import get_settings

logger = logging.getLogger(__name__)


async def send_alert_message(chat_id: str, symbol: str, price: float, condition: str) -> bool:
    """Send a price alert notification via Telegram Bot API."""
    settings = get_settings()
    if not settings.telegram_bot_token:
        logger.warning("TELEGRAM_BOT_TOKEN not configured — skipping Telegram notification")
        return False

    direction = "tăng vượt" if condition == "above" else "giảm xuống dưới"
    text = (
        f"🔔 *Cảnh báo cổ phiếu*\n\n"
        f"*{symbol}* đã {direction} mức giá *{price:,.1f}*\n\n"
        f"Vui lòng kiểm tra ứng dụng để biết thêm chi tiết."
    )

    url = f"https://api.telegram.org/bot{settings.telegram_bot_token}/sendMessage"
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(url, json={
                "chat_id": chat_id,
                "text": text,
                "parse_mode": "Markdown",
            })
            if resp.status_code != 200:
                logger.warning("Telegram API returned %d for chat_id=%s", resp.status_code, chat_id)
            return resp.status_code == 200
    except Exception as e:
        logger.error("Telegram send failed for chat_id=%s: %s", chat_id, e)
        return False
