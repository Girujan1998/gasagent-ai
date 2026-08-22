from fastapi import APIRouter, Depends, HTTPException

from app.models.schemas import ChatRequest, ChatResponse
from app.services.gemini_client import ChatError, ChatService, get_chat_service

router = APIRouter(prefix="/chat", tags=["chat"])


@router.post("", response_model=ChatResponse)
async def send_chat_message(
    request: ChatRequest,
    service: ChatService = Depends(get_chat_service),
) -> ChatResponse:
    """Send the conversation so far to the AI agent and return its reply."""
    location = (
        (request.location.lat, request.location.lon) if request.location else None
    )
    try:
        reply = await service.send(request.messages, location)
    except ChatError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return ChatResponse(message=reply)
