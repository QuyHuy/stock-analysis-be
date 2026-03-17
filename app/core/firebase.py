import firebase_admin
from firebase_admin import credentials, firestore, auth
from fastapi import HTTPException
from .config import get_settings


def init_firebase():
    settings = get_settings()
    if not firebase_admin._apps:
        cred = credentials.Certificate({
            "type": "service_account",
            "project_id": settings.firebase_project_id,
            "private_key": settings.firebase_private_key.replace("\\n", "\n"),
            "client_email": settings.firebase_client_email,
            "token_uri": "https://oauth2.googleapis.com/token",
        })
        firebase_admin.initialize_app(cred)
    return firestore.client()


_db = None


def get_db():
    global _db
    if _db is None:
        _db = init_firebase()
    return _db


def verify_token(authorization: str | None) -> str:
    """Verify Firebase ID token and return uid."""
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or invalid token")
    token = authorization.replace("Bearer ", "")
    try:
        decoded = auth.verify_id_token(token)
        return decoded["uid"]
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid token")
