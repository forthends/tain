"""Chat API routes — dialogue with agents via SSE."""

import asyncio
import json
import uuid
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from webui.data import get_agent
from webui.dialogue import (
    process_chat_message, _load_conversation_history,
    _active_cancel_events, cancel_chat_message,
)

router = APIRouter()


class ChatRequest(BaseModel):
    content: str


@router.get("/agent/{name}/chat/history")
async def api_chat_history(name: str, limit: int = 50):
    agent = get_agent(name)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    messages = _load_conversation_history(name)
    return {"messages": messages[-limit:], "total": len(messages)}


@router.post("/agent/{name}/chat")
async def api_chat_send(name: str, req: ChatRequest):
    agent = get_agent(name)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    message_id = f"msg_{uuid.uuid4().hex[:12]}"
    cancel_event = asyncio.Event()
    _active_cancel_events[message_id] = cancel_event

    async def generate():
        # Yield message_id first so frontend knows the cancel handle
        yield f"data: {json.dumps({'message_id': message_id}, ensure_ascii=False)}\n\n"

        try:
            async for event in process_chat_message(name, req.content, cancel_event):
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
        except asyncio.CancelledError:
            yield f"data: {json.dumps({'cancelled': True}, ensure_ascii=False)}\n\n"
        except Exception as e:
            import traceback
            tb = traceback.format_exc()
            yield f"data: {json.dumps({'error': str(e), 'traceback': tb[:500]}, ensure_ascii=False)}\n\n"
            print(f"[Chat error] {tb}", flush=True)
        finally:
            _active_cancel_events.pop(message_id, None)

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/agent/{name}/chat/cancel")
async def api_chat_cancel(name: str, message_id: str = Query(...)):
    """Cancel an in-progress chat stream."""
    agent = get_agent(name)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    cancelled = cancel_chat_message(message_id)
    return {"cancelled": cancelled, "message_id": message_id}
