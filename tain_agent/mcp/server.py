"""AgentMCPServer — MCP protocol server wrapping a Slim Kernel Agent."""
from __future__ import annotations
import json, sys, logging
from tain_agent import __version__
from tain_agent.mcp.middleware import ProductionGateMiddleware, RateLimiter
from tain_agent.mcp.endpoints import register_tools_endpoints, register_resource_endpoints, register_prompt_endpoints

logger = logging.getLogger(__name__)

class AgentMCPServer:
    def __init__(self, agent_name: str, max_tool_calls_per_minute: int = 60):
        self.agent_name = agent_name
        self._kernel = None
        self._gate = ProductionGateMiddleware()
        self._rate_limiter = RateLimiter(max_tool_calls_per_minute)
        self._handlers: dict = {}

    def serve(self, mode: str = "stdio") -> None:
        from tain_agent.kernel import AgentKernel, AgentContext
        from pathlib import Path
        import yaml
        config = {}
        try:
            with open("config.yaml") as f: config = yaml.safe_load(f)
        except Exception: pass
        workspace = Path("agent_workspace") / self.agent_name
        ctx = AgentContext(self.agent_name, self.agent_name, "ide", workspace, config, __version__)
        self._kernel = AgentKernel(ctx)
        factories = self._load_factories()
        self._kernel.load_plugins(factories)
        self._handlers.update(register_tools_endpoints(self._kernel))
        self._handlers.update(register_resource_endpoints(self._kernel))
        self._handlers.update(register_prompt_endpoints(self._kernel))
        logger.info("MCP Server started for '%s'", self.agent_name)
        if mode == "stdio":
            self._serve_stdio()

    def _serve_stdio(self):
        for line in sys.stdin:
            line = line.strip()
            if not line: continue
            try:
                req = json.loads(line)
                if isinstance(req, list):
                    responses = [self._handle_request(r) for r in req]
                    responses = [r for r in responses if r is not None]
                    if responses:
                        sys.stdout.write(json.dumps(responses, ensure_ascii=False) + "\n")
                        sys.stdout.flush()
                else:
                    resp = self._handle_request(req)
                    sys.stdout.write(json.dumps(resp, ensure_ascii=False) + "\n")
                    sys.stdout.flush()
            except json.JSONDecodeError:
                sys.stdout.write(json.dumps({"jsonrpc":"2.0","error":{"code":-32700,"message":"Parse error"},"id":None}) + "\n")
                sys.stdout.flush()

    def _handle_request(self, req: dict) -> dict:
        method = req.get("method", "")
        rid = req.get("id")
        if method == "tools/call" and not self._rate_limiter.allow("tools/call"):
            return {"jsonrpc":"2.0","error":{"code":-32000,"message":"Rate limit exceeded"},"id":rid}
        handler = self._handlers.get(method)
        if handler is None:
            return {"jsonrpc":"2.0","error":{"code":-32601,"message":f"Method not found: {method}"},"id":rid}
        try:
            params = req.get("params", {})
            result = handler(*params) if isinstance(params, list) else handler(**params)
            return {"jsonrpc":"2.0","result":result,"id":rid}
        except Exception as e:
            return {"jsonrpc":"2.0","error":{"code":-32000,"message":str(e)},"id":rid}

    def _load_factories(self):
        from tain_agent.plugins.identity import IdentityPlugin
        from tain_agent.plugins.tool import ToolPlugin
        from tain_agent.plugins.skill import SkillPlugin
        from tain_agent.plugins.knowledge import KnowledgePlugin
        from tain_agent.plugins.memory import MemoryPlugin
        return {"identity":IdentityPlugin,"tool":ToolPlugin,"skill":SkillPlugin,"knowledge":KnowledgePlugin,"memory":MemoryPlugin}
