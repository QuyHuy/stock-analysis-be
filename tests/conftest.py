from unittest.mock import MagicMock, patch


def _make_mock_settings():
    mock = MagicMock()
    mock.cors_origins = ["http://localhost:3000"]
    mock.firebase_project_id = "test-project"
    mock.firebase_private_key = "test-key"
    mock.firebase_client_email = "test@test.com"
    mock.gemini_api_key = "test-gemini-key"
    mock.telegram_bot_token = ""
    return mock


# Start patches at import time so they are active when test modules import app.main
_settings_patch = patch("app.core.config.get_settings", return_value=_make_mock_settings())
_firebase_patch = patch("app.core.firebase.init_firebase")
_settings_patch.start()
_firebase_patch.start()
