from unittest.mock import patch, MagicMock


def test_extract_symbols_finds_stock_codes():
    from app.services.gemini_service import extract_symbols
    result = extract_symbols("VNM đang ở vùng giá bao nhiêu? HPG có tốt không?")
    assert "VNM" in result
    assert "HPG" in result


def test_extract_symbols_filters_common_words():
    from app.services.gemini_service import extract_symbols
    result = extract_symbols("RSI của VNM là bao nhiêu? AI có nghĩ VIC tốt không?")
    assert "RSI" not in result
    assert "AI" not in result
    assert "VNM" in result
    assert "VIC" in result


def test_build_stock_context_with_data():
    from app.services.gemini_service import build_technical_context
    info = {"symbol": "VNM", "name": "Vinamilk", "exchange": "HOSE"}
    history = [{"date": "2026-03-17", "open": 79.0, "high": 82.0, "low": 78.0, "close": 81.0, "volume": 1000000}]
    context = build_technical_context("VNM", info, history)
    assert "VNM" in context
    assert "81" in context  # close price


def test_build_stock_context_empty_returns_string():
    from app.services.gemini_service import build_technical_context
    context = build_technical_context("VNM", {}, [])
    assert isinstance(context, str)
    assert len(context) > 0


def test_chat_endpoint_requires_auth():
    from fastapi.testclient import TestClient
    from app.main import app
    client = TestClient(app)
    response = client.post("/chat", json={"message": "test"})
    assert response.status_code == 401


def test_chat_endpoint_with_valid_token():
    from fastapi.testclient import TestClient
    from app.main import app

    with patch("app.core.firebase.auth") as mock_auth, \
         patch("app.services.gemini_service.chat_with_context", return_value="VNM đang ở 81 nghìn đồng."), \
         patch("app.services.firestore_service.save_chat_message"):
        mock_auth.verify_id_token.return_value = {"uid": "test-uid"}
        client = TestClient(app)
        response = client.post(
            "/chat",
            json={"message": "VNM giá bao nhiêu?"},
            headers={"Authorization": "Bearer fake-token"}
        )
    assert response.status_code == 200
    data = response.json()
    assert "reply" in data
    assert "chat_id" in data
    assert "VNM" in data.get("symbols_mentioned", [])
