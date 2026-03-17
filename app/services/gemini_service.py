import re
import logging
from functools import lru_cache
import google.generativeai as genai
from ..core.config import get_settings
from .firestore_service import get_latest_prices, get_stock_info

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """Bạn là chuyên gia phân tích chứng khoán Việt Nam với 15 năm kinh nghiệm, am hiểu sâu về phân tích kỹ thuật và cơ bản.

KHI CÓ DỮ LIỆU CỔ PHIẾU, hãy phân tích đầy đủ theo cấu trúc sau:

📊 **TỔNG QUAN**
- Giá hiện tại và thay đổi so với hôm qua, tuần trước, tháng trước (%)
- Khối lượng giao dịch so với trung bình 20 phiên

📈 **XU HƯỚNG & ĐƯỜNG TRUNG BÌNH**
- So sánh giá với MA20 và MA50: giá đang trên/dưới, khoảng cách %
- Nhận định xu hướng ngắn hạn (dưới 1 tháng) và trung hạn (1-3 tháng)
- Golden cross / Death cross nếu có

⚡ **CHỈ BÁO KỸ THUẬT**
- RSI(14): mức hiện tại và nhận định (quá mua >70, quá bán <30, trung tính)
- Biến động giá 5 phiên, 20 phiên
- Nhận xét về momentum

🎯 **VÙNG GIÁ QUAN TRỌNG**
- Vùng hỗ trợ gần nhất (dựa trên low gần đây)
- Vùng kháng cự gần nhất (dựa trên high gần đây)
- Khoảng % đến hỗ trợ/kháng cự

💡 **NHẬN ĐỊNH TỔNG THỂ**
- Đánh giá ngắn gọn: Tích cực / Trung tính / Thận trọng
- Điểm cần theo dõi trong phiên tới

⚠️ **CẢNH BÁO RỦI RO**
- Các rủi ro chính cần lưu ý

KHI KHÔNG CÓ DỮ LIỆU: Trả lời dựa trên kiến thức chung về doanh nghiệp/ngành, thông báo dữ liệu chưa được sync.

NGUYÊN TẮC:
- Trả lời bằng tiếng Việt, rõ ràng, có cấu trúc với emoji và markdown
- Dùng số liệu cụ thể, tránh chung chung
- Không đưa ra lời khuyên mua/bán tuyệt đối
- Luôn nhắc nhở về rủi ro và tự nghiên cứu thêm"""

_VN_STOCK_PATTERN = re.compile(r'\b([A-Z]{3,4})\b')
_COMMON_WORDS = frozenset({
    "AI", "OK", "VN", "TP", "HCM", "RSI", "MACD", "PE", "EPS", "ROE",
    "ROA", "IPO", "ETF", "NAV", "GDP", "CPI", "USD", "VND", "THE", "FOR",
    "MA", "SMA", "EMA", "ATH", "ATL",
})


def extract_symbols(text: str) -> list[str]:
    """Extract Vietnamese stock ticker symbols from user text."""
    candidates = _VN_STOCK_PATTERN.findall(text.upper())
    return [s for s in dict.fromkeys(candidates) if s not in _COMMON_WORDS]


def _calculate_indicators(history: list[dict]) -> dict:
    """Calculate technical indicators from price history (history is DESC order)."""
    if not history:
        return {}

    closes = [h.get("close", 0) for h in history]
    volumes = [h.get("volume", 0) for h in history]
    highs = [h.get("high", 0) for h in history]
    lows = [h.get("low", 0) for h in history]
    indicators = {}

    # Moving averages
    if len(closes) >= 20:
        indicators["ma20"] = sum(closes[:20]) / 20
    if len(closes) >= 50:
        indicators["ma50"] = sum(closes[:50]) / 50

    # RSI(14) — history is DESC so index 0 is latest
    if len(closes) >= 15:
        gains, losses = [], []
        for i in range(14):
            change = closes[i] - closes[i + 1]
            gains.append(max(change, 0))
            losses.append(max(-change, 0))
        avg_gain = sum(gains) / 14
        avg_loss = sum(losses) / 14
        if avg_loss > 0:
            rs = avg_gain / avg_loss
            indicators["rsi"] = round(100 - (100 / (1 + rs)), 1)
        else:
            indicators["rsi"] = 100.0

    # Volume average (20 sessions)
    if len(volumes) >= 20:
        indicators["vol_ma20"] = int(sum(volumes[:20]) / 20)

    # Price changes
    if len(closes) >= 2 and closes[1]:
        indicators["change_1d"] = round((closes[0] - closes[1]) / closes[1] * 100, 2)
    if len(closes) >= 6 and closes[5]:
        indicators["change_5d"] = round((closes[0] - closes[5]) / closes[5] * 100, 2)
    if len(closes) >= 21 and closes[20]:
        indicators["change_20d"] = round((closes[0] - closes[20]) / closes[20] * 100, 2)

    # Support / Resistance (recent 20 sessions)
    recent = history[:20]
    if recent:
        indicators["support"] = min(h.get("low", 0) for h in recent)
        indicators["resistance"] = max(h.get("high", 0) for h in recent)

    return indicators


def build_stock_context(stock_data: dict) -> str:
    """Build a detailed context string from Firestore data to inject into Gemini prompt."""
    if not stock_data:
        return "Không có dữ liệu cổ phiếu."

    parts = []
    info = stock_data.get("info") or {}
    symbol = info.get("symbol", "")

    if info:
        name = info.get("name", "")
        exchange = info.get("exchange", "")
        industry = info.get("industry", "")
        parts.append(f"=== {symbol}" + (f" - {name}" if name else "") + " ===")
        if exchange:
            parts.append(f"Sàn: {exchange}" + (f" | Ngành: {industry}" if industry else ""))

    history = stock_data.get("history") or []
    if not history:
        parts.append("Chưa có dữ liệu giá (cần sync dữ liệu)")
        return "\n".join(parts)

    latest = history[0]
    current_price = latest.get("close", 0)

    parts.append(f"\n--- Dữ liệu giá ({len(history)} phiên gần nhất) ---")
    parts.append(f"Ngày: {latest.get('date', '')}")
    parts.append(
        f"Mở: {latest.get('open', 0):,.1f} | Cao: {latest.get('high', 0):,.1f} | "
        f"Thấp: {latest.get('low', 0):,.1f} | Đóng: {current_price:,.1f}"
    )
    parts.append(f"Khối lượng: {latest.get('volume', 0):,}")

    ind = _calculate_indicators(history)

    # Price changes
    changes = []
    if "change_1d" in ind:
        changes.append(f"1 ngày: {ind['change_1d']:+.2f}%")
    if "change_5d" in ind:
        changes.append(f"5 ngày: {ind['change_5d']:+.2f}%")
    if "change_20d" in ind:
        changes.append(f"20 ngày: {ind['change_20d']:+.2f}%")
    if changes:
        parts.append(f"Biến động: {' | '.join(changes)}")

    # Moving averages
    if "ma20" in ind:
        diff_pct = (current_price - ind["ma20"]) / ind["ma20"] * 100
        trend = "trên" if current_price > ind["ma20"] else "dưới"
        parts.append(f"MA20: {ind['ma20']:,.1f} (giá {trend} MA20 {abs(diff_pct):.1f}%)")
    if "ma50" in ind:
        diff_pct = (current_price - ind["ma50"]) / ind["ma50"] * 100
        trend = "trên" if current_price > ind["ma50"] else "dưới"
        parts.append(f"MA50: {ind['ma50']:,.1f} (giá {trend} MA50 {abs(diff_pct):.1f}%)")

    # RSI
    if "rsi" in ind:
        rsi = ind["rsi"]
        signal = "⚠️ QUÁ MUA" if rsi > 70 else ("⚠️ QUÁ BÁN" if rsi < 30 else "trung tính")
        parts.append(f"RSI(14): {rsi} ({signal})")

    # Volume
    if "vol_ma20" in ind:
        vol_ratio = latest.get("volume", 0) / ind["vol_ma20"] if ind["vol_ma20"] else 0
        parts.append(f"Volume/TB20: {vol_ratio:.1f}x ({ind['vol_ma20']:,} TB)")

    # Support / Resistance
    if "support" in ind and "resistance" in ind:
        to_support = (current_price - ind["support"]) / current_price * 100
        to_resistance = (ind["resistance"] - current_price) / current_price * 100
        parts.append(
            f"Hỗ trợ: {ind['support']:,.1f} (-{to_support:.1f}%) | "
            f"Kháng cự: {ind['resistance']:,.1f} (+{to_resistance:.1f}%)"
        )

    # Raw data table (last 10 sessions for reference)
    parts.append(f"\n--- Lịch sử 10 phiên gần nhất ---")
    parts.append("Ngày       | Đóng cửa  | Khối lượng")
    for h in history[:10]:
        parts.append(
            f"{h.get('date', '')[:10]} | {h.get('close', 0):>9,.1f} | {h.get('volume', 0):>10,}"
        )

    return "\n".join(parts)


@lru_cache(maxsize=1)
def _get_gemini_model() -> genai.GenerativeModel:
    settings = get_settings()
    genai.configure(api_key=settings.gemini_api_key)
    return genai.GenerativeModel(
        model_name="gemini-2.5-flash",
        system_instruction=SYSTEM_PROMPT,
    )


def chat_with_context(user_message: str, history: list[dict] | None = None) -> str:
    """Call Gemini with rich stock data and technical indicators as context."""
    symbols = extract_symbols(user_message)

    context_parts = []
    for symbol in symbols[:5]:  # Support up to 5 symbols
        stock_data = {
            "info": get_stock_info(symbol),
            "history": get_latest_prices(symbol, limit=60),  # 60 days for better indicators
        }
        ctx = build_stock_context(stock_data)
        context_parts.append(ctx)

    if context_parts:
        context_str = "\n\n" + "\n\n".join(context_parts)
        full_message = f"{user_message}\n\n[DỮ LIỆU THỊ TRƯỜNG THỰC TẾ]{context_str}"
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
