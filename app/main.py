from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from .core.config import get_settings
from .core.firebase import get_db
from .routers import chat, stocks, alerts, sync


@asynccontextmanager
async def lifespan(app: FastAPI):
    get_db()  # Initialize Firebase Admin SDK at startup
    yield


app = FastAPI(title="Stock Analysis API", version="1.0.0", lifespan=lifespan)

settings = get_settings()
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(chat.router, prefix="/chat", tags=["chat"])
app.include_router(stocks.router, prefix="/stocks", tags=["stocks"])
app.include_router(alerts.router, prefix="/alerts", tags=["alerts"])
app.include_router(sync.router, prefix="/sync", tags=["sync"])


@app.get("/health")
def health():
    return {"status": "ok"}
