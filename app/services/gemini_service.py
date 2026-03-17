import re
import logging
from functools import lru_cache
import google.generativeai as genai
from ..core.config import get_settings
from .firestore_service import get_latest_prices, get_stock_info

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """Bạn là chuyên gia phân tích chứng khoán Việt Nam với 10 năm kinh nghiệm.
Hãy trả lời câu hỏi của nhà đầu tư dựa trên dữ liệu thực tế được cung cấp.
Trả lời bằng tiếng Việt, ngắn gọn, chính xác và hữu ích.
Nếu không có đủ dữ liệu, hãy nói rõ và đề xuất nhà đầu tư kiểm tra thêm.
QUAN TRỌNG: Không đưa ra lời khuyên đầu tư chắc chắn 100%, luôn nhắc nhở về rủi ro."""

_VN_STOCK_PATTERN = re.compile(r'\b([A-Z]{3,4})\b')
_COMMON_WORDS = frozenset({
    "AI", "OK", "VN", "TP", "HCM", "RSI", "MACD", "PE", "EPS", "ROE",
    "ROA", "IPO", "ETF", "NAV", "GDP", "CPI", "USD", "VND", "THE", "FOR",
})


def extract_symbols(text: str) -> list[str]:
    """Extract Vietnamese stock ticker symbols from user text."""
    candidates = _VN_STOCK_PATTERN.findall(text.upper())
    return [s for s in dict.fromkeys(candidates) if s not in _COMMON_WORDS]


def build_stock_context(stock_data: dict) -> str:
    """Build a context string from Firestore data to inject into Gemini prompt."""
    if not stock_data:
        return "Không có dữ liệu cổ phiếu."

    parts = []
    info = stock_data.get("info") or {}
    if info:
        parts.append(f"Cổ phiếu: {info.get('symbol', '')} - {info.get('name', '')}")
        if info.get("exchange"):
            parts.append(f"Sàn: {info['exchange']}")

    history = stock_data.get("history") or []
    if history:
        latest = history[0]
        parts.append(f"\nGiá gần nhất ({latest.get('date', '')}):")
        parts.append(f"  Mở cửa: {latest.get('open', 0):,.1f} | Cao: {latest.get('high', 0):,.1f}")
        parts.append(f"  Thấp: {latest.get('low', 0):,.1f} | Đóng cửa: {latest.get('close', 0):,.1f}")
        parts.append(f"  Khối lượng: {latest.get('volume', 0):,}")

        if len(history) >= 5:
            closes = [h.get("close", 0) for h in history[:5]]
            if closes[-1]:
                change = (closes[0] - closes[-1]) / closes[-1] * 100
                parts.append(f"  Biến động 5 phiên: {change:+.1f}%")

    return "\n".join(parts)


@lru_cache(maxsize=1)
def _get_gemini_model() -> genai.GenerativeModel:
    settings = get_settings()
    genai.configure(api_key=settings.gemini_api_key)
    return genai.GenerativeModel(
        model_name="gemini-2.0-flash",
        system_instruction=SYSTEM_PROMPT,
    )


def chat_with_context(user_message: str, history: list[dict] | None = None) -> str:
    """Call Gemini with relevant stock data from Firestore as context."""
    symbols = extract_symbols(user_message)

    context_parts = []
    for symbol in symbols[:3]:
        stock_data = {
            "info": get_stock_info(symbol),
            "history": get_latest_prices(symbol, limit=10),
        }
        context_parts.append(build_stock_context(stock_data))

    if context_parts:
        context_str = "\n\n---\n\n".join(context_parts)
        full_message = f"{user_message}\n\n[DỮ LIỆU THỊ TRƯỜNG]\n{context_str}"
    else:
        full_message = user_message

    model = _get_gemini_model()
    gemini_history = [
        {
            "role": "user" if msg["role"] == "user" else "model",
            "parts": [msg["content"]],
        }
        for msg in (history or [])
    ]
    chat = model.start_chat(history=gemini_history)
    response = chat.send_message(full_message)
    return response.text
