from pydantic import BaseModel
from typing import Literal


class ChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str


class ChatRequest(BaseModel):
    message: str
    chat_id: str | None = None
    history: list[ChatMessage] = []


class ChatResponse(BaseModel):
    reply: str
    chat_id: str
    symbols_mentioned: list[str] = []
