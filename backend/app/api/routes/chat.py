from fastapi import APIRouter, Depends, HTTPException

from app.models.schemas import ChatRequest, ChatResponse
from app.services.chat_agent_client import ChatError, ChatService, get_chat_service

router = APIRouter(prefix="/chat", tags=["chat"])


@router.post("", response_model=ChatResponse)
async def send_chat_message(
    request: ChatRequest,
    service: ChatService = Depends(get_chat_service),
) -> ChatResponse:
    """Send the conversation so far to the AI agent and return its reply."""
    gas_location = (
        (request.gas_location.lat, request.gas_location.lon)
        if request.gas_location
        else None
    )
    ev_location = (
        (request.ev_location.lat, request.ev_location.lon)
        if request.ev_location
        else None
    )
    try:
        result = await service.send(
            request.messages, gas_location=gas_location, ev_location=ev_location
        )
    except ChatError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return ChatResponse(
        message=result.message,
        gas_stations=result.gas_stations,
        ev_stations=result.ev_stations,
    )
