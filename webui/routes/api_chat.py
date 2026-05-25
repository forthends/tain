"""Chat API routes — dialogue with agents via SSE."""

import json
import asyncio
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from webui.data import get_agent
from webui.dialogue import process_chat_message, _load_conversation_history

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

    async def generate():
        try:
            async for event in process_chat_message(name, req.content):
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
        except Exception as e:
            import traceback
            tb = traceback.format_exc()
            yield f"data: {json.dumps({'error': str(e), 'traceback': tb[:500]}, ensure_ascii=False)}\n\n"
            # Log full traceback for server-side debugging
            print(f"[Chat error] {tb}", flush=True)

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
