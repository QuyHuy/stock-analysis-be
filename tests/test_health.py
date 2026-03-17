from fastapi.testclient import TestClient
from unittest.mock import patch, MagicMock


def get_mock_settings():
    mock = MagicMock()
    mock.cors_origins = ["http://localhost:3000"]
    mock.firebase_project_id = "test-project"
    mock.firebase_private_key = "test-key"
    mock.firebase_client_email = "test@test.com"
    mock.gemini_api_key = "test-gemini-key"
    mock.telegram_bot_token = ""
    return mock


with patch("app.core.config.get_settings", return_value=get_mock_settings()), \
     patch("app.core.firebase.init_firebase"):
    from app.main import app

client = TestClient(app)


def test_health():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
