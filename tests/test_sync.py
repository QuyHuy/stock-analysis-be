import pytest
import pandas as pd
from unittest.mock import patch, MagicMock


def test_get_stock_price_history_returns_records():
    mock_df = pd.DataFrame([{
        "time": "2026-03-17",
        "open": 80.0, "high": 82.0, "low": 79.0, "close": 81.0, "volume": 1000000
    }])
    with patch("app.services.vnstock_service.Vnstock") as mock_vnstock:
        mock_vnstock.return_value.stock.return_value.quote.history.return_value = mock_df
        from app.services.vnstock_service import get_stock_price_history
        result = get_stock_price_history("VNM", "2026-03-10", "2026-03-17")
    assert len(result) == 1
    assert result[0]["close"] == 81.0
    assert result[0]["date"] == "2026-03-17"


def test_get_stock_price_history_returns_empty_on_error():
    with patch("app.services.vnstock_service.Vnstock") as mock_vnstock:
        mock_vnstock.return_value.stock.return_value.quote.history.side_effect = Exception("API error")
        from app.services.vnstock_service import get_stock_price_history
        result = get_stock_price_history("INVALID", "2026-03-10", "2026-03-17")
    assert result == []


def test_get_stock_current_price_returns_float():
    mock_df = pd.DataFrame([{
        "time": "2026-03-17",
        "open": 80.0, "high": 82.0, "low": 79.0, "close": 81.5, "volume": 1000000
    }])
    with patch("app.services.vnstock_service.Vnstock") as mock_vnstock:
        mock_vnstock.return_value.stock.return_value.quote.history.return_value = mock_df
        from app.services.vnstock_service import get_stock_current_price
        result = get_stock_current_price("VNM")
    assert result == 81.5


def test_sync_endpoint_returns_200():
    """Sync endpoint trả 200; mock get_all_symbols để không gọi API (tránh rate limit)."""
    from fastapi.testclient import TestClient
    from app.main import app

    with (
        patch("app.routers.sync.get_all_symbols", return_value=["VNM"]),
        patch("app.routers.sync.get_stock_fundamentals") as mock_fund,
        patch("app.routers.sync.get_stock_price_history", return_value=[
            {"date": "2026-03-17", "open": 80, "high": 82, "low": 79, "close": 81, "volume": 1000},
        ]),
    ):
        mock_fund.return_value = {"symbol": "VNM", "name": "Vinamilk"}
        client = TestClient(app)
        response = client.post("/sync")
    assert response.status_code == 200
    assert "Sync started" in response.json()["message"]
