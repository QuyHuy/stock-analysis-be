import re
import logging
from functools import lru_cache
import google.generativeai as genai
from ..core.config import get_settings
from .firestore_service import get_latest_prices, get_stock_info

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """Bạn là chuyên gia phân tích chứng khoán Việt Nam với 15 năm kinh nghiệm, thành thạo cả phân tích kỹ thuật lẫn phân tích cơ bản.

─────────────────────────────────────────────
KHI ĐƯỢC CUNG CẤP DỮ LIỆU CỔ PHIẾU, hãy phân tích TOÀN DIỆN theo cấu trúc:

## 📊 TỔNG QUAN
- Tên công ty, sàn niêm yết, ngành
- Giá hiện tại và biến động (1 ngày / 5 ngày / 20 ngày)
- Vốn hóa thị trường (nếu có)

## 📈 PHÂN TÍCH KỸ THUẬT
**Xu hướng:**
- So sánh giá với MA20, MA50: đang trên/dưới bao nhiêu %
- Nhận định xu hướng ngắn hạn và trung hạn
- Tín hiệu Golden Cross / Death Cross nếu có

**Chỉ báo:**
- RSI(14): mức hiện tại → quá mua (>70) / quá bán (<30) / trung tính
- Volume hiện tại so với trung bình 20 phiên
- Momentum và sức mạnh xu hướng

**Vùng giá quan trọng:**
- Hỗ trợ gần nhất và xa hơn (tính từ low 20 phiên)
- Kháng cự gần nhất và xa hơn (tính từ high 20 phiên)
- Khoảng cách % đến hỗ trợ / kháng cự

## 💰 PHÂN TÍCH CƠ BẢN
**Định giá:**
- P/E, P/B, P/S so sánh với trung bình ngành
- EPS và BVPS hiện tại
- Nhận định cổ phiếu đang rẻ / hợp lý / đắt

**Chất lượng kinh doanh:**
- ROE, ROA: hiệu quả sử dụng vốn
- Biên lợi nhuận gộp và ròng
- Tăng trưởng doanh thu và lợi nhuận (YoY)

**Sức khỏe tài chính:**
- Nợ/Vốn chủ sở hữu (D/E ratio)
- Hệ số thanh khoản hiện hành
- Dòng tiền hoạt động kinh doanh

**Báo cáo tài chính (theo quý):**
- Xu hướng doanh thu và lợi nhuận qua các quý gần nhất
- Điểm đáng chú ý trong báo cáo

## 🎯 NHẬN ĐỊNH TỔNG HỢP
- Điểm mạnh của cổ phiếu
- Điểm yếu / rủi ro cần lưu ý
- Kết luận: Tích cực / Trung tính / Thận trọng (kèm lý do cụ thể)
- Mức giá cần theo dõi quan trọng

## ⚠️ CẢNH BÁO RỦI RO
- Rủi ro thị trường và ngành
- Rủi ro nội tại doanh nghiệp
- Các yếu tố macro cần theo dõi

─────────────────────────────────────────────
KHI KHÔNG CÓ DỮ LIỆU: Phân tích dựa trên kiến thức chung, thông báo rõ là chưa có dữ liệu thực tế.

NGUYÊN TẮC BẮT BUỘC:
- Trả lời bằng tiếng Việt, dùng markdown và emoji để dễ đọc
- Luôn dùng số liệu cụ thể từ dữ liệu được cung cấp
- KHÔNG đưa ra khuyến nghị mua/bán tuyệt đối
- Luôn nhắc nhở rủi ro và khuyến khích tự nghiên cứu thêm"""

_VN_STOCK_PATTERN = re.compile(r'\b([A-Z]{3,4})\b')
_COMMON_WORDS = frozenset({
    "AI", "OK", "VN", "TP", "HCM", "RSI", "MACD", "PE", "EPS", "ROE",
    "ROA", "IPO", "ETF", "NAV", "GDP", "CPI", "USD", "VND", "THE", "FOR",
    "MA", "SMA", "EMA", "ATH", "ATL", "TTM", "YOY", "QOQ",
})


def extract_symbols(text: str) -> list[str]:
    candidates = _VN_STOCK_PATTERN.findall(text.upper())
    return [s for s in dict.fromkeys(candidates) if s not in _COMMON_WORDS]


def _calculate_indicators(history: list[dict]) -> dict:
    """Calculate technical indicators (history is DESC — newest first)."""
    if not history:
        return {}
    closes  = [h.get("close", 0) for h in history]
    volumes = [h.get("volume", 0) for h in history]
    indicators = {}

    if len(closes) >= 20:
        indicators["ma20"] = round(sum(closes[:20]) / 20, 1)
    if len(closes) >= 50:
        indicators["ma50"] = round(sum(closes[:50]) / 50, 1)
    if len(closes) >= 100:
        indicators["ma100"] = round(sum(closes[:100]) / 100, 1)

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

    if len(volumes) >= 20:
        indicators["vol_ma20"] = int(sum(volumes[:20]) / 20)

    if len(closes) >= 2 and closes[1]:
        indicators["change_1d"]  = round((closes[0] - closes[1])  / closes[1]  * 100, 2)
    if len(closes) >= 6 and closes[5]:
        indicators["change_5d"]  = round((closes[0] - closes[5])  / closes[5]  * 100, 2)
    if len(closes) >= 21 and closes[20]:
        indicators["change_20d"] = round((closes[0] - closes[20]) / closes[20] * 100, 2)

    recent = history[:20]
    if recent:
        indicators["support"]    = min(h.get("low",  0) for h in recent)
        indicators["resistance"] = max(h.get("high", 0) for h in recent)

    return indicators


def _fmt(val, suffix="", decimals=1) -> str:
    if val is None:
        return "N/A"
    return f"{val:,.{decimals}f}{suffix}"


def build_technical_context(symbol: str, info: dict, history: list[dict]) -> str:
    parts = []
    name     = info.get("name", "")
    exchange = info.get("exchange", "")
    industry = info.get("industry", "")

    parts.append(f"╔══ {symbol}" + (f" — {name}" if name else "") + " ══╗")
    meta = []
    if exchange: meta.append(f"Sàn: {exchange}")
    if industry: meta.append(f"Ngành: {industry}")
    if meta:     parts.append(" | ".join(meta))

    if not history:
        parts.append("⚠ Chưa có dữ liệu giá lịch sử (cần trigger /sync)")
        return "\n".join(parts)

    latest = history[0]
    current = latest.get("close", 0)
    ind = _calculate_indicators(history)

    parts.append(f"\n[KỸ THUẬT — {len(history)} phiên]")
    parts.append(
        f"Ngày {latest.get('date','')} | "
        f"Mở: {_fmt(latest.get('open'))} | Cao: {_fmt(latest.get('high'))} | "
        f"Thấp: {_fmt(latest.get('low'))} | Đóng: {_fmt(current)}"
    )
    parts.append(f"Volume: {latest.get('volume', 0):,}")

    changes = []
    for key, label in [("change_1d","1D"), ("change_5d","5D"), ("change_20d","20D")]:
        if key in ind:
            arrow = "▲" if ind[key] > 0 else "▼"
            changes.append(f"{label}: {arrow}{abs(ind[key]):.2f}%")
    if changes:
        parts.append("Biến động: " + " | ".join(changes))

    for ma_key, ma_label in [("ma20","MA20"), ("ma50","MA50"), ("ma100","MA100")]:
        if ma_key in ind:
            diff = (current - ind[ma_key]) / ind[ma_key] * 100
            pos  = "↑trên" if current > ind[ma_key] else "↓dưới"
            parts.append(f"{ma_label}: {ind[ma_key]:,.1f} ({pos} {abs(diff):.1f}%)")

    if "rsi" in ind:
        rsi = ind["rsi"]
        sig = "🔴 QUÁ MUA" if rsi > 70 else ("🟢 QUÁ BÁN" if rsi < 30 else "🟡 Trung tính")
        parts.append(f"RSI(14): {rsi} — {sig}")

    if "vol_ma20" in ind and ind["vol_ma20"]:
        ratio = latest.get("volume", 0) / ind["vol_ma20"]
        parts.append(f"Volume/TB20: {ratio:.1f}x (TB: {ind['vol_ma20']:,})")

    if "support" in ind:
        to_sup = (current - ind["support"]) / current * 100
        to_res = (ind["resistance"] - current) / current * 100
        parts.append(
            f"Hỗ trợ: {ind['support']:,.1f} (-{to_sup:.1f}%) | "
            f"Kháng cự: {ind['resistance']:,.1f} (+{to_res:.1f}%)"
        )

    parts.append("\nGiá đóng cửa 15 phiên gần nhất:")
    parts.append("Ngày       | Đóng cửa  | Khối lượng")
    for h in history[:15]:
        parts.append(
            f"{h.get('date','')[:10]} | {h.get('close',0):>9,.1f} | {h.get('volume',0):>10,}"
        )

    return "\n".join(parts)


def build_fundamental_context(info: dict) -> str:
    parts = []
    has_data = False

    # ── Vốn hóa (nếu có) ────────────────────────────────────────────────────
    if info.get("market_cap") is not None:
        has_data = True
        parts.append(f"[TỔNG QUAN] Vốn hóa thị trường: {_fmt(info['market_cap'], '', 0)}")

    # ── Valuation ratios ──────────────────────────────────────────────────────
    valuation = []
    for key, label in [("pe","P/E"), ("pb","P/B"), ("ps","P/S"),
                        ("eps","EPS"), ("bvps","BVPS"), ("dividend_yield","Dividend Yield")]:
        if info.get(key) is not None:
            valuation.append(f"{label}: {info[key]}")
    if valuation:
        has_data = True
        parts.append("[CƠ BẢN — ĐỊNH GIÁ]")
        parts.append(" | ".join(valuation))

    # ── Profitability ─────────────────────────────────────────────────────────
    profit = []
    for key, label in [("roe","ROE"), ("roa","ROA"),
                        ("gross_margin","Biên gộp"), ("net_margin","Biên ròng"),
                        ("revenue_growth","Tăng trưởng DT"), ("profit_growth","Tăng trưởng LN")]:
        if info.get(key) is not None:
            profit.append(f"{label}: {info[key]}%")
    if profit:
        has_data = True
        parts.append("[HIỆU QUẢ KINH DOANH]")
        parts.append(" | ".join(profit))

    # ── Financial health ──────────────────────────────────────────────────────
    health = []
    for key, label in [("debt_equity","D/E"), ("current_ratio","Thanh khoản hiện hành")]:
        if info.get(key) is not None:
            health.append(f"{label}: {info[key]}")
    if health:
        has_data = True
        parts.append("[SỨC KHỎE TÀI CHÍNH]")
        parts.append(" | ".join(health))

    # ── Income statement ──────────────────────────────────────────────────────
    iq = info.get("income_quarters", [])
    if iq:
        has_data = True
        parts.append("[KẾT QUẢ KINH DOANH THEO QUÝ (tỷ VND)]")
        parts.append(f"{'Kỳ':10} | {'Doanh thu':>12} | {'Lợi nhuận gộp':>14} | {'LNST':>12} | {'LN hoạt động':>13}")
        for q in iq:
            parts.append(
                f"{str(q.get('period',''))[:10]:10} | "
                f"{_fmt(q.get('revenue'), ' tỷ', 0):>12} | "
                f"{_fmt(q.get('gross_profit'), ' tỷ', 0):>14} | "
                f"{_fmt(q.get('net_profit'), ' tỷ', 0):>12} | "
                f"{_fmt(q.get('operating_profit'), ' tỷ', 0):>13}"
            )

    # ── Balance sheet ─────────────────────────────────────────────────────────
    bq = info.get("balance_quarters", [])
    if bq:
        has_data = True
        parts.append("[BẢNG CÂN ĐỐI KẾ TOÁN THEO QUÝ (tỷ VND)]")
        parts.append(f"{'Kỳ':10} | {'Tổng tài sản':>14} | {'Tổng nợ':>10} | {'Vốn CSH':>10} | {'Tiền mặt':>10}")
        for q in bq:
            parts.append(
                f"{str(q.get('period',''))[:10]:10} | "
                f"{_fmt(q.get('total_assets'), ' tỷ', 0):>14} | "
                f"{_fmt(q.get('total_liabilities'), ' tỷ', 0):>10} | "
                f"{_fmt(q.get('equity'), ' tỷ', 0):>10} | "
                f"{_fmt(q.get('cash'), ' tỷ', 0):>10}"
            )

    # ── Cash flow ────────────────────────────────────────────────────────────
    cq = info.get("cashflow_quarters", [])
    if cq:
        has_data = True
        parts.append("[DÒNG TIỀN THEO QUÝ (tỷ VND)]")
        parts.append(f"{'Kỳ':10} | {'CF hoạt động':>14} | {'CF đầu tư':>11} | {'CF tài chính':>13} | {'FCF':>10}")
        for q in cq:
            parts.append(
                f"{str(q.get('period',''))[:10]:10} | "
                f"{_fmt(q.get('operating_cf'), ' tỷ', 0):>14} | "
                f"{_fmt(q.get('investing_cf'), ' tỷ', 0):>11} | "
                f"{_fmt(q.get('financing_cf'), ' tỷ', 0):>13} | "
                f"{_fmt(q.get('free_cash_flow'), ' tỷ', 0):>10}"
            )

    if not has_data:
        return ""

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
    """Call Gemini with full technical + fundamental data as context."""
    symbols = extract_symbols(user_message)

    context_blocks = []
    for symbol in symbols[:5]:
        info    = get_stock_info(symbol) or {}
        prices  = get_latest_prices(symbol, limit=100)

        tech_ctx  = build_technical_context(symbol, info, prices)
        fund_ctx  = build_fundamental_context(info)

        block = tech_ctx
        if fund_ctx:
            block += "\n\n" + fund_ctx
        context_blocks.append(block)

    if context_blocks:
        context_str = "\n\n" + ("\n\n" + "─" * 60 + "\n\n").join(context_blocks)
        full_message = (
            f"{user_message}"
            f"\n\n{'═' * 60}"
            f"\n[DỮ LIỆU THỊ TRƯỜNG THỰC TẾ — Phân tích kỹ thuật + cơ bản]"
            f"{context_str}"
        )
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
