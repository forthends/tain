"""Agent data and control API routes — return JSON."""

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from webui.agent_cache import invalidate_agent

from webui.data import (
    list_agents, get_agent, get_agent_decisions,
    get_agent_tools, get_agent_tool_detail, get_agent_evolution,
    get_agent_metrics, get_agent_personality, get_agent_knowledge,
    get_agent_knowledge_content, get_agent_goals, is_agent_running,
)
from webui.process import ProcessManager

router = APIRouter()


@router.get("/agents")
async def api_list_agents():
    return {"agents": list_agents()}


@router.get("/agent/{name}/overview")
async def api_agent_overview(name: str):
    agent = get_agent(name)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    goals = get_agent_goals(name)
    return {"agent": agent, "goals": goals}


@router.get("/agent/{name}/decisions")
async def api_agent_decisions(name: str, phase: str = "", type: str = "",
                               limit: int = 20, offset: int = 0):
    entries, total = get_agent_decisions(name, phase=phase, decision_type=type,
                                          limit=limit, offset=offset)
    return {"decisions": entries, "total": total, "limit": limit, "offset": offset}


@router.get("/agent/{name}/tools")
async def api_agent_tools(name: str):
    return {"tools": get_agent_tools(name)}


@router.get("/agent/{name}/tools/{tool_name}")
async def api_agent_tool_detail(name: str, tool_name: str):
    tool = get_agent_tool_detail(name, tool_name)
    if not tool:
        raise HTTPException(status_code=404, detail="Tool not found")
    return tool


@router.get("/agent/{name}/evolution")
async def api_agent_evolution(name: str):
    return {"events": get_agent_evolution(name)}


@router.get("/agent/{name}/metrics")
async def api_agent_metrics(name: str):
    return {"metrics": get_agent_metrics(name)}


@router.get("/agent/{name}/personality")
async def api_agent_personality(name: str):
    personality = get_agent_personality(name)
    if not personality:
        raise HTTPException(status_code=404, detail="Personality data not found")
    return personality


@router.get("/agent/{name}/knowledge")
async def api_agent_knowledge(name: str):
    return {"files": get_agent_knowledge(name)}


@router.get("/agent/{name}/knowledge/content")
async def api_agent_knowledge_content(name: str, path: str):
    fmt, content = get_agent_knowledge_content(name, path)
    return {"format": fmt, "content": content}


@router.post("/agent/{name}/start")
async def api_agent_start(name: str):
    result = ProcessManager().start(name)
    return {"success": result.success, "output": result.stdout, "error": result.stderr}


@router.post("/agent/{name}/stop")
async def api_agent_stop(name: str):
    result = ProcessManager().stop(name)
    return {"success": result.success, "output": result.stdout, "error": result.stderr}


@router.post("/agent/{name}/restart")
async def api_agent_restart(name: str):
    stop_result, start_result = ProcessManager().restart(name)
    return {
        "success": start_result.success,
        "stop_output": stop_result.stdout,
        "output": start_result.stdout,
        "error": start_result.stderr,
    }


@router.post("/agent/{name}/reload")
async def reload_agent(name: str):
    """Force reload a cached agent instance."""
    was_cached = invalidate_agent(name)
    return {
        "success": True,
        "agent": name,
        "was_cached": was_cached,
        "message": "Agent cache cleared" if was_cached else "Agent was not in cache",
    }


class CreateAgentRequest(BaseModel):
    name: str
    mode: str = "chaos"
    role: str = ""
    role_description: str = ""


@router.post("/agents/create")
async def api_create_agent(req: CreateAgentRequest):
    from tain_agent.core.agent_factory import AgentFactory
    from tain_agent import __version__ as fw_version

    factory = AgentFactory()
    if factory.exists(req.name):
        raise HTTPException(status_code=400, detail=f"Agent '{req.name}' already exists.")

    result = factory.create(
        name=req.name,
        mode=req.mode,
        role=req.role,
        role_description=req.role_description,
        framework_version=fw_version,
    )
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])

    return {"success": True, "name": req.name, "mode": req.mode, "message": f"Agent '{req.name}' created."}
