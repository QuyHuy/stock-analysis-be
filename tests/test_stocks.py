from unittest.mock import patch, MagicMock


def test_list_stocks_requires_auth():
    from fastapi.testclient import TestClient
    from app.main import app
    client = TestClient(app)
    response = client.get("/stocks")
    assert response.status_code == 401


def test_list_stocks_returns_symbols():
    from fastapi.testclient import TestClient
    from app.main import app
    with patch("app.core.firebase.auth") as mock_auth:
        mock_auth.verify_id_token.return_value = {"uid": "test-uid"}
        client = TestClient(app)
        response = client.get("/stocks", headers={"Authorization": "Bearer fake-token"})
    assert response.status_code == 200
    data = response.json()
    assert "symbols" in data
    assert "VNM" in data["symbols"]


def test_get_stock_requires_auth():
    from fastapi.testclient import TestClient
    from app.main import app
    client = TestClient(app)
    response = client.get("/stocks/VNM")
    assert response.status_code == 401


def test_get_stock_returns_data():
    from fastapi.testclient import TestClient
    from app.main import app
    mock_info = {"symbol": "VNM", "name": "Vinamilk", "exchange": "HOSE"}
    mock_prices = [{"date": "2026-03-17", "close": 81.0, "volume": 1000000}]

    with patch("app.core.firebase.auth") as mock_auth, \
         patch("app.services.firestore_service.get_stock_info", return_value=mock_info), \
         patch("app.services.firestore_service.get_latest_prices", return_value=mock_prices):
        mock_auth.verify_id_token.return_value = {"uid": "test-uid"}
        client = TestClient(app)
        response = client.get("/stocks/VNM", headers={"Authorization": "Bearer fake-token"})
    assert response.status_code == 200
    data = response.json()
    assert data["info"]["symbol"] == "VNM"
    assert len(data["history"]) == 1


def test_get_stock_not_found():
    from fastapi.testclient import TestClient
    from app.main import app
    with patch("app.core.firebase.auth") as mock_auth, \
         patch("app.services.firestore_service.get_stock_info", return_value=None):
        mock_auth.verify_id_token.return_value = {"uid": "test-uid"}
        client = TestClient(app)
        response = client.get("/stocks/NOTEXIST", headers={"Authorization": "Bearer fake-token"})
    assert response.status_code == 404
