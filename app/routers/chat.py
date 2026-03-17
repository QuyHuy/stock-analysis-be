import uuid
import logging
from fastapi import APIRouter, HTTPException, Header
from ..models.chat import ChatRequest, ChatResponse
from ..services import gemini_service
from ..services import firestore_service
from ..core.firebase import verify_token

router = APIRouter()
logger = logging.getLogger(__name__)


@router.get("/history")
async def list_chats(authorization: str | None = Header(default=None)):
    """Get list of recent chat sessions for the authenticated user."""
    uid = verify_token(authorization)
    return firestore_service.get_user_chats(uid)


@router.get("/history/{chat_id}")
async def get_chat(
    chat_id: str,
    authorization: str | None = Header(default=None),
):
    """Get all messages for a specific chat session."""
    uid = verify_token(authorization)
    messages = firestore_service.get_chat_messages(uid, chat_id)
    return {"chat_id": chat_id, "messages": messages}


@router.post("", response_model=ChatResponse)
async def chat(
    request: ChatRequest,
    authorization: str | None = Header(default=None),
):
    uid = verify_token(authorization)
    chat_id = request.chat_id or str(uuid.uuid4())

    try:
        history = [{"role": m.role, "content": m.content} for m in request.history]
        reply = gemini_service.chat_with_context(request.message, history)
        symbols = gemini_service.extract_symbols(request.message)
        firestore_service.save_chat_message(uid, chat_id, "user", request.message)
        firestore_service.save_chat_message(uid, chat_id, "assistant", reply)
        return ChatResponse(reply=reply, chat_id=chat_id, symbols_mentioned=symbols)
    except HTTPException:
        raise
    except Exception as e:
        error_str = str(e)
        logger.error("Chat error for uid=%s: %s", uid, e)
        if "429" in error_str or "quota" in error_str.lower() or "resource exhausted" in error_str.lower():
            raise HTTPException(
                status_code=429,
                detail="AI đang quá tải, vui lòng thử lại sau vài giây.",
            )
        raise HTTPException(status_code=500, detail="Lỗi xử lý câu hỏi")
