# Backend Rules

## Tech Stack
- Python 3.12, FastAPI, Pydantic v2
- Firebase Admin SDK for Firestore
- Google Generative AI SDK for Gemini (gemini-2.0-flash)
- vnstock for Vietnamese stock data

## Conventions
- All endpoints validate Firebase ID token via Authorization header using verify_token() from app/core/firebase.py
- Pydantic models in app/models/
- Business logic in app/services/
- Route handlers in app/routers/ (thin, delegate to services)
- Use async functions for I/O bound operations
- Environment variables via app/core/config.py Settings class (pydantic-settings)

## Firestore Collections
- /stocks/{symbol} - stock basic info
- /stocks/{symbol}/history/{YYYY-MM-DD} - daily OHLCV data
- /stocks/{symbol}/indicators/{YYYY-MM-DD} - technical indicators
- /users/{uid} - user profile + watchlist
- /users/{uid}/chats/{chatId}/messages/{msgId} - chat history
- /alerts/{alertId} - price alerts

## Error Handling
- Use HTTPException with appropriate status codes
- Log errors with Python logging module, not print()
- Never expose internal error details in production responses
