"""
Tín hiệu kỹ thuật / định tính từ lịch sử giá (rule-based, không phải tư vấn đầu tư).
"""
import logging
from typing import Any

logger = logging.getLogger(__name__)

_EX_ORDER = ("HOSE", "HNX", "UPCOM", "Khác")


def normalize_exchange(ex: str | None) -> str:
    if not ex:
        return "HOSE"
    u = str(ex).strip().upper()
    if u in ("HSX", "HO CHI MINH", "HOSE"):
        return "HOSE"
    if u in ("HNX", "HA NOI"):
        return "HNX"
    if u in ("UPCOM", "UPC"):
        return "UPCOM"
    return u if u in ("HOSE", "HNX", "UPCOM") else "HOSE"


def tradingview_symbol(symbol: str, exchange: str | None) -> str:
    """TradingView format: HOSE:VNM"""
    ex = normalize_exchange(exchange)
    if ex == "Khác":
        ex = "HOSE"
    return f"{ex}:{symbol.upper()}"


def _calc_rsi(closes: list[float], period: int = 14) -> float | None:
    if len(closes) < period + 1:
        return None
    gains, losses = [], []
    for i in range(period):
        ch = closes[i] - closes[i + 1]
        gains.append(max(ch, 0))
        losses.append(max(-ch, 0))
    avg_l = sum(losses) / period
    if avg_l <= 0:
        return 100.0
    avg_g = sum(gains) / period
    rs = avg_g / avg_l
    return round(100 - (100 / (1 + rs)), 1)


def compute_signals(history_desc: list[dict], info: dict) -> dict[str, Any]:
    """
    history_desc: mới nhất trước (giống Firestore get_latest_prices).
    """
    out: dict[str, Any] = {
        "stance": "Trung tính",
        "stance_key": "neutral",
        "score": 0,
        "indicators": [],
        "warnings": [],
        "opportunities": [],
        "disclaimer": (
            "Các chỉ báo chỉ hỗ trợ tham khảo, không phải khuyến nghị mua/bán. "
            "Luôn tự nghiên cứu và quản trị rủi ro."
        ),
    }
    if not history_desc or len(history_desc) < 5:
        out["warnings"].append("Chưa đủ dữ liệu giá lịch sử để tính chỉ báo kỹ thuật (cần sync).")
        return out

    closes = [float(h.get("close") or 0) for h in history_desc]
    volumes = [int(h.get("volume") or 0) for h in history_desc]
    if not closes[0] or not closes[1]:
        return out

    score = 0
    ind = []
    warns = []
    opps = []

    # Biến động
    ch1 = (closes[0] - closes[1]) / closes[1] * 100 if closes[1] else 0
    ind.append({"label": "Biến động 1 phiên", "value": f"{ch1:+.2f}%"})

    if len(closes) >= 6 and closes[5]:
        ch5 = (closes[0] - closes[5]) / closes[5] * 100
        ind.append({"label": "5 phiên", "value": f"{ch5:+.2f}%"})
        if ch5 < -8:
            warns.append("Giảm mạnh trong 5 phiên gần đây — xu hướng ngắn hạn yếu.")
            score -= 1
        elif ch5 > 8:
            opps.append("Tăng mạnh 5 phiên — đà ngắn hạn tích cực (đề phòng chốt lời).")
            score += 1

    if len(closes) >= 21 and closes[20]:
        ch20 = (closes[0] - closes[20]) / closes[20] * 100
        ind.append({"label": "20 phiên", "value": f"{ch20:+.2f}%"})
        if ch20 < -15:
            warns.append("Giảm >15% trong ~1 tháng — rủi ro xu hướng giảm trung hạn.")
            score -= 2
        elif ch20 < -7:
            warns.append("Giá đang trong nhịp điều chỉnh (~1 tháng). Theo dõi hỗ trợ.")
            score -= 1
        elif ch20 > 15:
            opps.append("Tăng trưởng giá tốt trong ~1 tháng — xu hướng tích cực.")
            score += 1

    ma20 = sum(closes[:20]) / 20 if len(closes) >= 20 else None
    ma50 = sum(closes[:50]) / 50 if len(closes) >= 50 else None
    if ma20:
        ind.append({"label": "MA20", "value": f"{ma20:,.0f}"})
        dist = (closes[0] - ma20) / ma20 * 100
        if closes[0] > ma20:
            ind.append({"label": "So với MA20", "value": f"+{dist:.1f}% (trên MA20)"})
            score += 1
            if ma50 and ma20 > ma50:
                opps.append("Giá trên MA20 và MA20 > MA50 — xu hướng trung hạn thuận.")
                score += 1
        else:
            ind.append({"label": "So với MA20", "value": f"{dist:.1f}% (dưới MA20)"})
            score -= 1
            warns.append("Giá dưới MA20 — sức mạnh ngắn hạn đang yếu.")
    if ma50:
        ind.append({"label": "MA50", "value": f"{ma50:,.0f}"})

    rsi = _calc_rsi(closes)
    if rsi is not None:
        ind.append({"label": "RSI(14)", "value": str(rsi)})
        if rsi < 30:
            opps.append(f"RSI ~{rsi}: vùng quá bán — có thể hồi kỹ thuật (không chắc đảo chiều).")
            score += 1
        elif rsi > 70:
            warns.append(f"RSI ~{rsi}: vùng quá mua — dễ điều chỉnh ngắn hạn.")
            score -= 1

    if len(volumes) >= 21:
        vol_ma = sum(volumes[1:21]) / 20
        if vol_ma and volumes[0] > vol_ma * 1.5:
            ind.append({"label": "Volume", "value": f"{volumes[0] / vol_ma:.1f}x TB20"})
            if ch1 > 0:
                opps.append("Khối lượng cao kèm tăng giá — dòng tiền vào rõ.")
            elif ch1 < 0:
                warns.append("Khối lượng cao kèm giảm giá — áp lực bán mạnh.")

    # P/E định tính
    pe = info.get("pe")
    if pe is not None and pe > 0:
        if pe < 8:
            opps.append(f"P/E ~{pe}: định giá tương đối thấp (so sánh ngành trước khi quyết định).")
        elif pe > 25:
            warns.append(f"P/E ~{pe}: định giá cao — kỳ vọng tăng trưởng đã phản ánh vào giá.")

    out["score"] = max(-5, min(5, score))
    if out["score"] >= 2:
        out["stance"] = "Nhiều tín hiệu tích cực (chỉ tham khảo)"
        out["stance_key"] = "positive"
    elif out["score"] <= -2:
        out["stance"] = "Thận trọng — nhiều tín hiệu yếu/rủi ro"
        out["stance_key"] = "caution"
    else:
        out["stance"] = "Trung tính — mixed signals"
        out["stance_key"] = "neutral"

    out["indicators"] = ind
    out["warnings"] = warns
    out["opportunities"] = opps
    return out


def fetch_kbs_live_row(symbol: str, exchange: str | None) -> dict[str, Any] | None:
    """Bảng giá KBS: NN mua/bán, giá khớp…"""
    sym = symbol.upper()
    ex_pref = normalize_exchange(exchange)
    order = [ex_pref, "HOSE", "HNX", "UPCOM"]
    seen = []
    for e in order:
        if e not in seen:
            seen.append(e)
    try:
        from vnstock.api.trading import Trading
        t = Trading(source="kbs", symbol=sym, show_log=False)
        for ex in seen:
            try:
                df = t.price_board([sym], exchange=ex, get_all=True)
            except Exception:
                continue
            if df is None or df.empty:
                continue
            sym_col = "symbol" if "symbol" in df.columns else None
            if sym_col:
                row_df = df[df[sym_col].astype(str).str.upper() == sym]
            else:
                row_df = df.head(1)
            if row_df.empty:
                continue
            r = row_df.iloc[0]
            def g(*keys):
                for k in keys:
                    if k in r.index:
                        v = r[k]
                        if v is not None and str(v) not in ("nan", "NaT"):
                            return v
                return None

            fb = g("foreign_buy_volume", "FB")
            fs = g("foreign_sell_volume", "FR")
            try:
                fbn = float(fb or 0)
                fsn = float(fs or 0)
            except (TypeError, ValueError):
                fbn = fsn = 0
            return {
                "exchange_board": ex,
                "match_price": _num(g("close_price", "match_price", "CP")),
                "reference_price": _num(g("reference_price", "RE")),
                "ceiling_price": _num(g("ceiling_price", "CL")),
                "floor_price": _num(g("floor_price", "FL")),
                "total_volume": _num(g("total_trades", "TT")),
                "total_value_bil": _num(g("total_value", "TV")),
                "foreign_buy_volume": int(fbn) if fbn else None,
                "foreign_sell_volume": int(fsn) if fsn else None,
                "foreign_net_volume": int(fbn - fsn) if (fb is not None or fs is not None) else None,
                "percent_change": _num(g("percent_change", "CHP")),
            }
    except Exception as e:
        logger.debug("KBS board %s: %s", sym, e)
    return None


def _num(v):
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None
