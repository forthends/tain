"""
ACP Server — Agent Communication Protocol over stdio transport.

Wraps a Tain agent as an ACP-compatible server that external editors
(Zed, custom clients) can embed. Uses JSON-RPC 2.0 over stdin/stdout.

Protocol flow:
  initialize → newSession → prompt (streaming) → cancel/closeSession

Run: python -m tain_agent.acp
"""

import asyncio
import json
import os
import signal
import sys
import traceback
import uuid
from pathlib import Path
from typing import Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


class ACPServer:
    """ACP-compatible server over stdio transport.

    Manages agent sessions and routes JSON-RPC requests to the
    appropriate handlers. Each session wraps a Tain agent instance.
    """

    def __init__(self, config_path: str = ""):
        self.config_path = config_path or str(PROJECT_ROOT / "config.yaml")
        self.sessions: dict[str, dict] = {}  # session_id → {agent, cancel_event, ...}
        self._running = False
        self._request_id = 0

    # ── Main loop ──────────────────────────────────────────────────

    async def run(self) -> None:
        """Run the ACP server, reading JSON-RPC from stdin."""
        self._running = True
        reader = asyncio.StreamReader()
        loop = asyncio.get_event_loop()
        await loop.connect_read_pipe(
            lambda: asyncio.StreamReaderProtocol(reader),
            sys.stdin,
        )

        while self._running:
            try:
                line = await asyncio.wait_for(
                    reader.readline(), timeout=3600
                )
                if not line:
                    break

                request = json.loads(line.decode("utf-8").strip())
                response = await self._handle_request(request)

                if response is not None:
                    sys.stdout.write(json.dumps(response, ensure_ascii=False) + "\n")
                    sys.stdout.flush()

            except asyncio.TimeoutError:
                continue
            except json.JSONDecodeError:
                continue
            except EOFError:
                break
            except Exception as e:
                err_resp = {
                    "jsonrpc": "2.0",
                    "id": None,
                    "error": {"code": -32603, "message": str(e)},
                }
                sys.stdout.write(json.dumps(err_resp, ensure_ascii=False) + "\n")
                sys.stdout.flush()

    async def _handle_request(self, request: dict) -> Optional[dict]:
        """Route a JSON-RPC request to the appropriate handler."""
        req_id = request.get("id")
        method = request.get("method", "")
        params = request.get("params", {})

        handlers = {
            "initialize": self._handle_initialize,
            "newSession": self._handle_new_session,
            "prompt": self._handle_prompt,
            "cancel": self._handle_cancel,
            "closeSession": self._handle_close_session,
        }

        handler = handlers.get(method)
        if handler is None:
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "error": {"code": -32601, "message": f"Method not found: {method}"},
            }

        try:
            result = await handler(params, req_id)
            return result
        except Exception as e:
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "error": {"code": -32603, "message": f"{type(e).__name__}: {e}"},
            }

    # ── RPC handlers ───────────────────────────────────────────────

    async def _handle_initialize(self, params: dict, req_id) -> dict:
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "protocolVersion": "2025-01-01",
                "serverInfo": {
                    "name": "tain-agent-acp",
                    "version": "0.5.0",
                },
                "capabilities": {
                    "streaming": True,
                    "cancellation": True,
                },
            },
        }

    async def _handle_new_session(self, params: dict, req_id) -> dict:
        session_id = f"acp_{uuid.uuid4().hex[:12]}"
        workspace_path = params.get("workspace_path", "")

        if workspace_path:
            os.makedirs(workspace_path, exist_ok=True)

        self.sessions[session_id] = {
            "workspace_path": workspace_path,
            "created_at": _now_iso(),
            "cancel_event": asyncio.Event(),
        }

        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "session_id": session_id,
                "workspace_path": workspace_path,
            },
        }

    async def _handle_prompt(self, params: dict, req_id) -> dict:
        session_id = params.get("session_id", "")
        text = params.get("text", "")

        session = self.sessions.get(session_id)
        if not session:
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "error": {"code": -32000, "message": f"Session not found: {session_id}"},
            }

        # Send initial response to ack the prompt
        sys.stdout.write(json.dumps({
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {"status": "processing"},
        }, ensure_ascii=False) + "\n")
        sys.stdout.flush()

        cancel_event = session["cancel_event"]

        try:
            from webui.dialogue import process_chat_message

            agent_name = f"acp_session_{session_id[:8]}"
            events = process_chat_message(
                agent_name=agent_name,
                user_content=text,
                cancel_event=cancel_event,
            )

            async for event in events:
                if cancel_event.is_set():
                    self._send_event(session_id, {"type": "cancelled"})
                    break

                acp_event = self._convert_to_acp_event(event)
                self._send_event(session_id, acp_event)

                if event.get("done"):
                    break

        except Exception as e:
            self._send_event(session_id, {
                "type": "error",
                "error": f"{type(e).__name__}: {e}",
            })

        self._send_event(session_id, {"type": "done"})
        return None  # Response already sent as streaming events

    async def _handle_cancel(self, params: dict, req_id) -> dict:
        session_id = params.get("session_id", "")
        session = self.sessions.get(session_id)

        cancelled = False
        if session:
            event = session.get("cancel_event")
            if event and not event.is_set():
                event.set()
                cancelled = True

        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "session_id": session_id,
                "cancelled": cancelled,
            },
        }

    async def _handle_close_session(self, params: dict, req_id) -> dict:
        session_id = params.get("session_id", "")
        session = self.sessions.pop(session_id, None)

        if session:
            event = session.get("cancel_event")
            if event:
                event.set()

        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "session_id": session_id,
                "closed": session is not None,
            },
        }

    # ── Event helpers ───────────────────────────────────────────────

    def _send_event(self, session_id: str, event: dict) -> None:
        """Send a streaming event to stdout."""
        event["session_id"] = session_id
        sys.stdout.write(json.dumps(event, ensure_ascii=False) + "\n")
        sys.stdout.flush()

    def _convert_to_acp_event(self, sse_event: dict) -> dict:
        """Convert an SSE event from process_chat_message to ACP format."""
        event_type = "content"

        if "cancelled" in sse_event:
            event_type = "cancelled"
        elif sse_event.get("status") == "thinking":
            event_type = "thinking"
        elif sse_event.get("status") == "text":
            event_type = "text_start"
        elif "text" in sse_event:
            event_type = "text_delta"
        elif "tool_start" in sse_event:
            return {
                "type": "tool_call",
                "tool": sse_event["tool_start"],
            }
        elif "tool_done" in sse_event:
            event_type = "tool_done"
        elif "done" in sse_event:
            event_type = "done"
        elif "status" in sse_event:
            event_type = sse_event["status"]

        result = {"type": event_type}
        if "text" in sse_event:
            result["text"] = sse_event["text"]
            result["length"] = len(sse_event["text"])
        if "message_id" in sse_event:
            result["message_id"] = sse_event["message_id"]

        return result


def _now_iso() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()


# ── Entry point ──────────────────────────────────────────────────────────


async def main() -> None:
    """Entry point for `python -m tain_agent.acp`."""
    config_path = sys.argv[1] if len(sys.argv) > 1 else ""
    server = ACPServer(config_path=config_path)

    # Handle graceful shutdown
    loop = asyncio.get_event_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, lambda: setattr(server, '_running', False))
        except NotImplementedError:
            pass

    await server.run()


if __name__ == "__main__":
    asyncio.run(main())
