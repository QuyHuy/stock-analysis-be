#!/usr/bin/env python3
"""
Chạy script này (với Python đã cài vnstock) để in ra tên cột thực tế từ TCBS.

Cách chạy ĐÚNG (từ thư mục stock-analysis-be, sau khi cài requirements):

  cd stock-analysis-be
  python3 -m venv .venv && source .venv/bin/activate   # Windows: .venv\\Scripts\\activate
  pip install -r requirements.txt
  python scripts/debug_tcbs_columns.py

Hoặc cài nhanh vào Python hiện tại: pip install vnstock pandas
"""
import sys
from pathlib import Path

# Thư mục stock-analysis-be (cha của scripts/)
_BE_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_BE_ROOT))


def main():
    try:
        from vnstock import Vnstock
    except ModuleNotFoundError:
        exe = sys.executable
        print(
            "ModuleNotFoundError: chưa cài vnstock cho Python này.\n"
            f"  Python đang dùng: {exe}\n\n"
            "Cài vào venv backend (khuyến nghị):\n"
            f"  cd {_BE_ROOT}\n"
            "  python3 -m venv .venv && source .venv/bin/activate\n"
            "  pip install -r requirements.txt\n"
            "  python scripts/debug_tcbs_columns.py\n\n"
            "Hoặc: pip install vnstock pandas\n",
            file=sys.stderr,
        )
        sys.exit(1)
    symbol = "VNM"
    stock = Vnstock().stock(symbol=symbol, source="TCBS")

    print("=== Company overview (TCBS) ===")
    ov = stock.company.overview()
    if ov is not None and not ov.empty:
        print("Columns:", list(ov.columns))
        print("Row 0:", ov.iloc[0].to_dict())
    else:
        print("Empty or None")

    print("\n=== Finance ratio quarter (TCBS) ===")
    r = stock.finance.ratio(period="quarter", lang="en")
    if r is not None and not r.empty:
        print("Columns:", list(r.columns))
        print("Row 0:", r.iloc[0].to_dict())
    else:
        print("Empty or None")

    print("\n=== Listing (all symbols) ===")
    try:
        from vnstock.explorer.vci.listing import Listing
        L = Listing()
        df = L.all_symbols()
        print("Columns:", list(df.columns) if df is not None else "None")
        print("Count:", len(df) if df is not None else 0)
        if df is not None and not df.empty:
            print("Sample:", df.head(3).to_string())
    except Exception as e:
        print("Error:", e)


if __name__ == "__main__":
    main()
