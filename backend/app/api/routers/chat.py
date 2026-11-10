"""问答接口：流式（SSE）与非流式两种调用方式，以及会话历史。"""
import json

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse

from app.api.deps import get_chat_service, get_container
from app.api.schemas import ChatRequest
from app.container import Container
from app.services.chat_service import ChatService

router = APIRouter(prefix="/api/chat")


def sse_event(payload: dict) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False, default=str)}\n\n"


@router.post("/stream")
async def chat_stream(body: ChatRequest, service: ChatService = Depends(get_chat_service)) -> StreamingResponse:
    """提问并以 SSE 接收过程与回答。"""
    async def events():
        async for event in service.stream(body.query, body.session_id):
            yield sse_event(event)

    return StreamingResponse(events(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@router.post("")
async def chat(body: ChatRequest, service: ChatService = Depends(get_chat_service)) -> dict:
    """提问并等待完整回答（不需要逐字显示时使用）。"""
    result = await service.ask(body.query, body.session_id)
    if result.get("type") == "error":
        raise HTTPException(status_code=502, detail=result["message"])
    result.pop("type", None)
    return result


@router.get("/history/{session_id}")
async def get_history(session_id: str, limit: int = 50, container: Container = Depends(get_container)) -> dict:
    messages = await container.history.recent(session_id, max(1, min(limit, 200)))
    return {"session_id": session_id, "items": [
        {"role": message["role"], "text": message["text"], "products": message.get("products", []),
         "sources": message.get("sources", []), "ts": message["ts"]}
        for message in messages
    ]}


@router.delete("/history/{session_id}")
async def clear_history(session_id: str, container: Container = Depends(get_container)) -> dict:
    return {"deleted": await container.history.clear(session_id)}
