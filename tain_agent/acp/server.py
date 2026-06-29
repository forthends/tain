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
import yaml
from pathlib import Path

from typing import Optional

from tain_agent import __version__
from tain_agent.runtime import AgentRuntime
from tain_agent.package import PackageRegistry, PackageKind

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


class _ACPAgentAdapter:
    """Minimal adapter so ChatEngine can use AgentRuntime."""
    def __init__(self, kernel, agent_name, config):
        self.kernel = kernel
        self.agent_name = agent_name
        self.config = config
        tool_plugin = kernel.get_plugin("ToolPlugin")
        self.tools = tool_plugin
        identity_plugin = kernel.get_identity()
        self.personality = identity_plugin.personality if identity_plugin else None
        from tain_agent.core.llm import LLMBackend
        backend_config = config.get("llm", {})
        # LLMBackend takes (model, max_tokens) — extract from config
        model = backend_config.get("model", "claude-sonnet-4-6")
        max_tokens = backend_config.get("max_tokens", 4096)
        self.backend = LLMBackend(model, max_tokens)
        if backend_config.get("api_key_env"):
            self.backend.api_key_env = backend_config["api_key_env"]

    def _execute_tool_calls(self, tool_calls):
        results = []
        for tc in tool_calls:
            result = self.kernel.dispatch.call("tool.call", tc.name, **tc.input)
            content = str(result) if result is not None else f"Tool '{tc.name}' returned no result"
            results.append({"tool_use_id": tc.id, "content": content})
        return results


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
                    "version": __version__,
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
            # Validate path does not escape agent_workspace/
            resolved = Path(workspace_path).resolve()
            workspace_root = (PROJECT_ROOT / "agent_workspace").resolve()
            try:
                resolved.relative_to(workspace_root)
            except ValueError:
                return {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "error": {
                        "code": -32001,
                        "message": (
                            f"workspace_path must be within agent_workspace/. "
                            f"Got: {workspace_path}"
                        ),
                    },
                }
            os.makedirs(resolved, exist_ok=True)
            workspace_path = str(resolved)

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
            from tain_agent.core.chat import ChatEngine

            agent_name = f"acp_session_{session_id[:8]}"
            workspace = (PROJECT_ROOT / "agent_workspace") / agent_name
            workspace.mkdir(parents=True, exist_ok=True)

            with open(self.config_path) as f:
                config = yaml.safe_load(f) or {}

            ctx = AgentContext(
                agent_name=agent_name,
                agent_id=f"{agent_name}-{workspace.name}",
                evolution_mode=config.get("agent", {}).get("evolution_mode", "specified"),
                workspace_path=workspace,
                config=config,
                kernel_version=__version__,
            )
            reg = PackageRegistry(packages_root=PROJECT_ROOT / "agent_workspace" / "packages")
            pkg = reg.get_package(agent_name)
            if pkg is None:
                pkg = reg.create(name=agent_name, kind=PackageKind.AGENT)
            kernel = AgentRuntime(package=pkg, config=config)

            # Wrap kernel as chat-compatible adapter
            agent = _ACPAgentAdapter(kernel, agent_name, config)
            engine = ChatEngine(agent)

            messages = [{"role": "user", "content": text}]
            final_turn = None
            async for event in engine.run_turn(messages, cancel_event):
                if event["type"] == "done":
                    final_turn = event["turn"]

            if final_turn:
                self._send_event(session_id, {"type": "text", "text": final_turn.text})
                for tc in final_turn.tool_calls:
                    self._send_event(session_id, {"type": "tool_call", "name": tc.name, "input": tc.input})
            if cancel_event.is_set():
                self._send_event(session_id, {"type": "cancelled"})

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
