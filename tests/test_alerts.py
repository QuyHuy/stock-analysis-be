from unittest.mock import patch, MagicMock
import pytest


def test_create_alert_requires_auth():
    from fastapi.testclient import TestClient
    from app.main import app
    client = TestClient(app)
    response = client.post("/alerts", json={"symbol": "VNM", "condition": "above", "price": 85.0})
    assert response.status_code == 401


def test_create_alert_with_valid_token():
    from fastapi.testclient import TestClient
    from app.main import app
    mock_db = MagicMock()
    mock_doc_ref = MagicMock()
    mock_doc_ref.id = "test-alert-id"
    mock_db.collection.return_value.document.return_value = mock_doc_ref

    with patch("app.core.firebase.auth") as mock_auth, \
         patch("app.core.firebase.get_db", return_value=mock_db):
        mock_auth.verify_id_token.return_value = {"uid": "test-uid"}
        client = TestClient(app)
        response = client.post(
            "/alerts",
            json={"symbol": "VNM", "condition": "above", "price": 85.0},
            headers={"Authorization": "Bearer fake-token"}
        )
    assert response.status_code == 200
    data = response.json()
    assert data["symbol"] == "VNM"
    assert data["condition"] == "above"
    assert data["price"] == 85.0
    assert data["active"] is True


def test_list_alerts_requires_auth():
    from fastapi.testclient import TestClient
    from app.main import app
    client = TestClient(app)
    response = client.get("/alerts")
    assert response.status_code == 401


def test_check_alerts_endpoint():
    from fastapi.testclient import TestClient
    from app.main import app
    with patch("app.services.firestore_service.get_active_alerts", return_value=[]):
        client = TestClient(app)
        response = client.post("/alerts/check")
    assert response.status_code == 200
    assert "Alert check started" in response.json()["message"]
