import logging
import re
from datetime import datetime, timedelta, timezone
from vnstock import Vnstock

logger = logging.getLogger(__name__)

# Đa nguồn theo tài liệu Vnstock: https://vnstocks.com/docs/vnstock
# — VCI: listing GraphQL + price/symbols; KBS: listing đầy đủ mã cổ phiếu.
# Fundamentals: ưu tiên VCI, bổ sung KBS khi thiếu chỉ số.
SOURCE_FUNDAMENTALS = "VCI"

DEFAULT_SYMBOLS = [
    "VNM", "VIC", "VHM", "VCB", "BID", "CTG", "TCB", "MBB", "HPG", "HSG",
    "FPT", "VRE", "MSN", "GAS", "SAB", "PLX", "HDB", "VPB", "ACB", "STB",
    "EIB", "SSI", "VND", "MWG", "PNJ", "DGC", "GEX", "REE", "NLG", "KDH",
    "VCI", "DXG", "BCM", "VGC", "PHR", "CSV", "PDR", "DIG", "CII", "SZC",
    "BWE", "DCM", "DPM", "GVR", "HAH", "HCM", "IDC", "IJC", "IMP", "KBC",
]


def _is_equity_symbol(sym: str) -> bool:
    s = str(sym).strip().upper()
    if not s or len(s) < 2 or len(s) > 5:
        return False
    if not s.isalpha():
        return False
    # Loại mã phái sinh / đặc biệt phổ biến
    if s.startswith("VN30") or s.endswith("F1M") or s.startswith("41"):
        return False
    return True


def get_all_symbols() -> list[str]:
    """
    Gộp mã cổ phiếu từ nhiều nguồn vnstock (VCI + KBS) để đủ toàn thị trường.
    - VCI symbols_by_exchange (type STOCK, không phân biệt hoa thường)
    - VCI symbols_by_industries (CompaniesListingInfo — thường >1000 mã)
    - KBS all_symbols (type stock)
    """
    merged: set[str] = set()
    log_parts: list[str] = []

    def add_from_series(series, tag: str) -> int:
        n = 0
        for sym in series:
            if _is_equity_symbol(sym):
                s = str(sym).strip().upper()
                if s not in merged:
                    n += 1
                merged.add(s)
        if n or merged:
            log_parts.append(f"{tag}:+{n}")
        return n

    # 1) VCI — bảng niêm yết theo sàn (đủ type)
    try:
        from vnstock.explorer.vci.listing import Listing as VCIListing
        L = VCIListing()
        df = L.symbols_by_exchange(lang="vi", show_log=False)
        if df is not None and not df.empty and "symbol" in df.columns:
            if "type" in df.columns:
                t = df["type"].astype(str).str.upper().str.strip()
                skip = {"CW", "ETF", "BOND", "FU_INDEX", "INDEX", "COVERED_WARRANT"}
                mask = t == "STOCK"
                if mask.sum() < 200:
                    mask = ~t.isin(skip) & df["symbol"].astype(str).str.match(r"^[A-Z]{2,5}$", na=False)
                syms = df.loc[mask, "symbol"] if mask.any() else df["symbol"]
            else:
                syms = df["symbol"]
            add_from_series(syms, "VCI_exchange")
    except Exception as e:
        logger.warning("VCI symbols_by_exchange: %s", e)

    # 2) VCI — toàn bộ mã doanh nghiệp (GraphQL)
    try:
        from vnstock.explorer.vci.listing import Listing as VCIListing
        df2 = VCIListing().symbols_by_industries(lang="vi", show_log=False)
        if df2 is not None and not df2.empty and "symbol" in df2.columns:
            add_from_series(df2["symbol"], "VCI_companies")
    except Exception as e:
        logger.warning("VCI symbols_by_industries: %s", e)

    # 3) KBS — danh sách cổ phiếu
    try:
        from vnstock.explorer.kbs.listing import Listing as KBSListing
        df3 = KBSListing().all_symbols(show_log=False)
        if df3 is not None and not df3.empty and "symbol" in df3.columns:
            add_from_series(df3["symbol"], "KBS")
    except Exception as e:
        logger.warning("KBS all_symbols: %s", e)

    if len(merged) >= 150:
        out = sorted(merged)
        logger.info("get_all_symbols merged %d symbols (%s)", len(out), " ".join(log_parts))
        return out

    # 4) Fallback VCI all_symbols() (chỉ STOCK — có thể ít mã nếu API lỗi)
    try:
        from vnstock.explorer.vci.listing import Listing as VCIListing
        df4 = VCIListing().all_symbols(show_log=False)
        if df4 is not None and not df4.empty and "symbol" in df4.columns:
            add_from_series(df4["symbol"], "VCI_all_symbols")
    except Exception as e:
        logger.warning("VCI all_symbols: %s", e)

    if merged:
        out = sorted(merged)
        logger.info("get_all_symbols partial %d (%s)", len(out), " ".join(log_parts))
        return out

    logger.warning("No listing API succeeded; using DEFAULT_SYMBOLS (%d)", len(DEFAULT_SYMBOLS))
    return list(DEFAULT_SYMBOLS)


def _safe_float(val) -> float | None:
    try:
        return round(float(val), 2) if val is not None and val == val else None
    except (TypeError, ValueError):
        return None


def _safe_int(val) -> int | None:
    try:
        return int(float(val)) if val is not None and val == val else None
    except (TypeError, ValueError):
        return None


def _get_row_value(row, *candidates):
    """Lấy giá trị đầu tiên khác None/nan từ row với danh sách tên cột."""
    for col in candidates:
        val = row.get(col) if hasattr(row, "get") else getattr(row, col, None)
        if val is not None and str(val) not in ("nan", "None", ""):
            return val
    return None


def _row_to_dict(row, mapping: dict) -> dict:
    """Extract fields from a DataFrame row using a key mapping."""
    result = {}
    for out_key, candidates in mapping.items():
        cols = candidates if isinstance(candidates, list) else [candidates]
        val = _get_row_value(row, *cols)
        if val is not None:
            result[out_key] = val
    return result


def _vci_flat_row_keys(row) -> dict:
    """Chuyển một dòng VCI (có thể MultiIndex column) thành dict key cuối cùng -> giá trị."""
    out = {}
    for k in row.index:
        key = k[-1] if isinstance(k, tuple) else k
        out[str(key)] = row[k]
    return out


def _pick_col_by_label(row, rdf, patterns: list[tuple[str, list[str]]]) -> float | None:
    """
    Tìm cột theo regex trên nhãn cột (hỗ trợ MultiIndex).
    patterns: [(regex, [substring_exclude]), ...]
    """
    for col in rdf.columns:
        parts = col if isinstance(col, tuple) else (col,)
        label = " | ".join(str(p) for p in parts).lower()
        for regex, excludes in patterns:
            if any(ex in label for ex in excludes):
                continue
            if re.search(regex, label, re.I):
                v = row[col]
                if v is not None and v == v and str(v) not in ("nan", "None", ""):
                    return _safe_float(v)
    return None


def _merge_valuation_from_vci_ratio(result: dict, rdf) -> None:
    """Bổ sung pe, pb, ps, eps, bvps, roe, roa từ DataFrame ratio VCI (cột phân cấp)."""
    if rdf is None or rdf.empty:
        return
    row = rdf.iloc[0]
    picks = {
        "pe": [(r"p\s*/\s*e(\s|$|[^a-z])", ["eps", "opportunity", "forward"]), (r"^pe$", ["eps"])],
        "pb": [(r"p\s*/\s*b", []), (r"\bpb\b", ["bvps"])],
        "ps": [(r"p\s*/\s*s", []), (r"\bps\b", ["eps"])],
        "eps": [(r"(^|\s)eps(\s|$|ttm)", ["bvps", "growth"]), (r"\beps\b", ["bvps", "pe"])],
        "bvps": [(r"bvps", []), (r"book\s*value\s*per\s*share", [])],
        "roe": [(r"(^|\s)roe(\s|$)", ["growth"])],
        "roa": [(r"(^|\s)roa(\s|$)", [])],
        "gross_margin": [(r"gross\s*margin", []), (r"gross\s*profit\s*margin", [])],
        "net_margin": [(r"net\s*profit\s*margin", []), (r"net\s*margin", ["gross"])],
        "revenue_growth": [(r"revenue\s*growth", [])],
        "profit_growth": [(r"(net\s*)?profit\s*growth", []), (r"earning\s*growth", [])],
        "debt_equity": [(r"debt.*equity", []), (r"d\s*/\s*e\s*ratio", [])],
        "current_ratio": [(r"current\s*ratio", ["quick"])],
        "dividend_yield": [(r"dividend\s*yield", []), (r"\bdividend\b", ["yield"])],
    }
    for field, pat_list in picks.items():
        if result.get(field) is not None:
            continue
        for regex, excl in pat_list:
            v = _pick_col_by_label(row, rdf, [(regex, excl)])
            if v is not None:
                result[field] = v
                break


def _merge_valuation_from_vci_overview(result: dict, row) -> None:
    """VCI overview: financialRatio flatten -> pe, pb, eps, bvps, ps, roe, roa."""
    d = row.to_dict() if hasattr(row, "to_dict") else {}
    exact = {
        "pe": "pe", "pb": "pb", "ps": "ps", "eps": "eps", "bvps": "bvps",
        "roe": "roe", "roa": "roa",
    }
    for out, ek in exact.items():
        if result.get(out) is not None:
            continue
        for k, v in d.items():
            if str(k).lower() == ek:
                sf = _safe_float(v)
                if sf is not None:
                    result[out] = sf
                break
    if result.get("market_cap") is None:
        for mk in ("market_cap", "market_capital", "capitalization"):
            for k, v in d.items():
                if str(k).lower() == mk:
                    result["market_cap"] = _safe_float(v)
                    break
            if result.get("market_cap") is not None:
                break


def _history_to_records(df) -> list[dict]:
    if df is None or df.empty:
        return []
    df = df.reset_index()
    records = []
    for _, row in df.iterrows():
        date_val = (
            row.get("time") or row.get("date") or row.get("Date") or row.get("Time")
        )
        if date_val is None and hasattr(df, "index") and df.index.name in ("time", "date"):
            date_val = row.name
        records.append({
            "date": str(date_val)[:10] if date_val is not None else "",
            "open": float(row.get("open") or row.get("Open") or 0),
            "high": float(row.get("high") or row.get("High") or 0),
            "low": float(row.get("low") or row.get("Low") or 0),
            "close": float(row.get("close") or row.get("Close") or 0),
            "volume": int(row.get("volume") or row.get("Volume") or 0),
        })
    return [r for r in records if r["date"]]


def get_stock_price_history(symbol: str, start_date: str, end_date: str) -> list[dict]:
    """Lịch sử giá: VCI → KBS → TCBS (theo độ ổn định vnstock 3.5)."""
    for src in ("VCI", "KBS", "TCBS"):
        try:
            stock = Vnstock().stock(symbol=symbol, source=src)
            df = stock.quote.history(start=start_date, end=end_date, interval="1D")
            rec = _history_to_records(df)
            if rec:
                return rec
        except Exception as e:
            logger.debug("Quote %s via %s: %s", symbol, src, e)
    logger.warning("Empty history for %s (%s to %s)", symbol, start_date, end_date)
    return []


def _vci_income_row_to_quarter(flat: dict) -> dict | None:
    """Map một dòng KQKD VCI (tiếng Anh) sang dict chuẩn."""
    meta_skip = {"ticker", "symbol", "cp", "yearreport", "lengthreport", "năm", "kỳ"}
    yr = flat.get("yearReport") or flat.get("Năm")
    lq = flat.get("lengthReport") or flat.get("Kỳ")
    if yr is None and lq is None:
        return None
    q: dict = {"period": f"{yr or ''}/{lq or ''}".strip("/")}
    for k, v in flat.items():
        kl = k.lower().replace(" ", "")
        if kl in meta_skip:
            continue
        try:
            num = float(v)
        except (TypeError, ValueError):
            continue
        if num == 0 and kl not in ("yearreport", "lengthreport"):
            pass
        kl_full = k.lower()
        if "netrevenue" in kl or kl_full == "revenue" or "doanhthuthuần" in kl:
            q["revenue"] = _safe_float(num / 1e9)
        elif "grossprofit" in kl or "lợinhuậngộp" in kl:
            q["gross_profit"] = _safe_float(num / 1e9)
        elif "ebit" in kl and "margin" not in kl:
            q["operating_profit"] = _safe_float(num / 1e9)
        elif "profitaftertax" in kl or "netprofit" in kl or "lnst" in kl or "lợinhuậnsauthuế" in kl:
            q["net_profit"] = _safe_float(num / 1e9)
        elif "ebitda" in kl:
            q["ebitda"] = _safe_float(num / 1e9)
    return q if len(q) > 1 else None


def _vci_balance_row_to_quarter(flat: dict) -> dict | None:
    yr = flat.get("yearReport") or flat.get("Năm")
    lq = flat.get("lengthReport") or flat.get("Kỳ")
    if yr is None and lq is None:
        return None
    q: dict = {"period": f"{yr or ''}/{lq or ''}".strip("/")}
    for k, v in flat.items():
        kl = k.lower()
        try:
            num = float(v)
        except (TypeError, ValueError):
            continue
        if "totalasset" in kl.replace(" ", "") or "tổngtàisản" in kl.replace(" ", ""):
            q["total_assets"] = _safe_float(num / 1e9)
        elif "totalliabilit" in kl.replace(" ", "") or "tổngnợ" in kl.replace(" ", ""):
            q["total_liabilities"] = _safe_float(num / 1e9)
        elif kl.replace(" ", "") in ("equity", "vốnchủsởhữu", "ownersequity"):
            q["equity"] = _safe_float(num / 1e9)
        elif "cash" in kl and "equivalent" in kl:
            q["cash"] = _safe_float(num / 1e9)
    return q if len(q) > 1 else None


def _vci_cashflow_row_to_quarter(flat: dict) -> dict | None:
    yr = flat.get("yearReport") or flat.get("Năm")
    lq = flat.get("lengthReport") or flat.get("Kỳ")
    if yr is None and lq is None:
        return None
    q: dict = {"period": f"{yr or ''}/{lq or ''}".strip("/")}
    for k, v in flat.items():
        kl = k.lower()
        try:
            num = float(v)
        except (TypeError, ValueError):
            continue
        if "operating" in kl and "cash" in kl:
            q["operating_cf"] = _safe_float(num / 1e9)
        elif "investing" in kl and "cash" in kl:
            q["investing_cf"] = _safe_float(num / 1e9)
        elif "financing" in kl and "cash" in kl:
            q["financing_cf"] = _safe_float(num / 1e9)
        elif "freecash" in kl.replace(" ", ""):
            q["free_cash_flow"] = _safe_float(num / 1e9)
    return q if len(q) > 1 else None


def get_stock_fundamentals(symbol: str) -> dict:
    """
    Lấy dữ liệu cơ bản từ VCI (vnstock 3.5 — TCBS không còn cho Finance).
    Gồm: overview (P/E, P/B, EPS…), ratio bổ sung, KQKD / CĐKT / LCTT theo quý.
    """
    result: dict = {"symbol": symbol}
    try:
        stock = Vnstock().stock(symbol=symbol, source=SOURCE_FUNDAMENTALS)

        # ── Company overview (VCI: pe, pb, eps trong financialRatio) ─────────
        try:
            df = stock.company.overview()
            if df is not None and not df.empty:
                row = df.iloc[0]
                result["name"] = str(
                    _get_row_value(row, "organ_name", "en_organ_name", "short_name", "company_name") or ""
                )
                result["exchange"] = str(
                    _get_row_value(row, "com_group_code", "exchange", "floor") or ""
                )
                result["industry"] = str(
                    _get_row_value(row, "icb_name3", "icb_name2", "industry_name", "industry") or ""
                )
                _merge_valuation_from_vci_overview(result, row)
                if result.get("market_cap") is None:
                    mcap = _get_row_value(row, "market_cap", "market_capital")
                    if mcap is not None:
                        result["market_cap"] = _safe_float(mcap)
            else:
                logger.debug("Overview empty for %s", symbol)
        except Exception as e:
            logger.warning("Overview failed %s: %s", symbol, e)

        # ── Ratio VCI: bảng MultiIndex — quét nhãn cột P/E, P/B… ─────────────
        try:
            rdf = None
            try:
                rdf = stock.finance.ratio(
                    period="quarter", lang="en", dropna=False,
                    flatten_columns=True, separator=" | ",
                )
            except Exception:
                rdf = stock.finance.ratio(period="quarter", lang="en", dropna=False)
            if rdf is not None and not rdf.empty:
                _merge_valuation_from_vci_ratio(result, rdf)
            else:
                logger.debug("Ratio empty for %s", symbol)
        except Exception as e:
            logger.warning("Ratios failed %s: %s", symbol, e)

        # ── Income statement ───────────────────────────────────────────────────
        try:
            idf = stock.finance.income_statement(period="quarter", lang="en", dropna=False)
            if idf is not None and not idf.empty:
                quarters = []
                for _, row in idf.head(8).iterrows():
                    q = _vci_income_row_to_quarter(_vci_flat_row_keys(row))
                    if q:
                        quarters.append(q)
                if quarters:
                    result["income_quarters"] = quarters
        except Exception as e:
            logger.warning("Income statement failed %s: %s", symbol, e)

        # ── Balance sheet ─────────────────────────────────────────────────────
        try:
            bdf = stock.finance.balance_sheet(period="quarter", lang="en", dropna=False)
            if bdf is not None and not bdf.empty:
                quarters = []
                for _, row in bdf.head(4).iterrows():
                    q = _vci_balance_row_to_quarter(_vci_flat_row_keys(row))
                    if q:
                        quarters.append(q)
                if quarters:
                    result["balance_quarters"] = quarters
        except Exception as e:
            logger.warning("Balance sheet failed %s: %s", symbol, e)

        # ── Cash flow ─────────────────────────────────────────────────────────
        try:
            cdf = stock.finance.cash_flow(period="quarter", lang="en", dropna=False)
            if cdf is not None and not cdf.empty:
                quarters = []
                for _, row in cdf.head(4).iterrows():
                    q = _vci_cashflow_row_to_quarter(_vci_flat_row_keys(row))
                    if q:
                        quarters.append(q)
                if quarters:
                    result["cashflow_quarters"] = quarters
        except Exception as e:
            logger.warning("Cash flow failed %s: %s", symbol, e)

    except Exception as e:
        logger.warning("Could not fetch fundamentals for %s: %s", symbol, e)

    result.setdefault("data_sources_fundamentals", ["VCI"])
    if (result.get("pe") is None and result.get("pb") is None) or not result.get("name"):
        _merge_fundamentals_from_kbs(result, symbol)

    return result


def _merge_fundamentals_from_kbs(result: dict, symbol: str) -> None:
    """Bổ sung chỉ số / tên từ KBS khi VCI thiếu (đa nguồn)."""
    try:
        from vnstock import Finance
        kf = Finance(source="kbs", symbol=symbol, show_log=False)
        df = kf.ratio(period="quarter", show_log=False)
        if df is None or df.empty:
            return
        item_col = "item" if "item" in df.columns else None
        if not item_col:
            return
        val_cols = [c for c in df.columns if c != item_col and c not in ("item_id",)]
        last_col = val_cols[-1] if val_cols else None
        if not last_col:
            return
        for _, row in df.iterrows():
            lab = str(row.get(item_col, "")).lower()
            v = _safe_float(row.get(last_col))
            if v is None:
                continue
            if ("p/e" in lab or "hệ số p/e" in lab or lab.strip() in ("pe", "p e")) and result.get("pe") is None:
                result["pe"] = v
            elif ("p/b" in lab or "hệ số p/b" in lab) and result.get("pb") is None:
                result["pb"] = v
            elif ("p/s" in lab or "hệ số p/s" in lab) and result.get("ps") is None:
                result["ps"] = v
            elif ("eps" in lab and "bvps" not in lab) and result.get("eps") is None:
                result["eps"] = v
            elif "bvps" in lab or "bvcps" in lab or "book value" in lab:
                if result.get("bvps") is None:
                    result["bvps"] = v
            elif "roe" in lab and "growth" not in lab and result.get("roe") is None:
                result["roe"] = v
        if "KBS" not in result["data_sources_fundamentals"]:
            result["data_sources_fundamentals"].append("KBS")
    except ValueError:
        pass
    except Exception as e:
        logger.debug("KBS fundamentals overlay %s: %s", symbol, e)


def get_stock_current_price(symbol: str) -> float | None:
    """Fetch the most recent closing price for a stock."""
    now = datetime.now(timezone.utc)
    today = now.strftime("%Y-%m-%d")
    week_ago = (now - timedelta(days=7)).strftime("%Y-%m-%d")
    records = get_stock_price_history(symbol, week_ago, today)
    if records:
        return records[-1]["close"]
    return None
