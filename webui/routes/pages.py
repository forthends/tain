"""Page routes — return HTML."""

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from pathlib import Path
from jinja2 import Environment, FileSystemLoader

from webui.data import (
    list_agents, get_agent, get_config, get_agent_goals,
    get_agent_decisions, get_agent_tools, get_agent_evolution,
    get_agent_metrics, get_agent_personality, get_agent_knowledge,
)

router = APIRouter()
TEMPLATE_DIR = str(Path(__file__).resolve().parent.parent / "templates")
_jinja_env = Environment(loader=FileSystemLoader(TEMPLATE_DIR), autoescape=True)


def _render(template_name: str, context: dict) -> HTMLResponse:
    template = _jinja_env.get_template(template_name)
    return HTMLResponse(template.render(**context))


@router.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    agents = list_agents()
    cfg = get_config()
    framework_version = cfg.get("framework", {}).get("version", "0.4.1")
    llm_provider = cfg.get("llm", {}).get("provider", "unknown")
    llm_model = cfg.get("llm", {}).get("model", "unknown")
    return _render("dashboard.html", {
        "request": request,
        "agents": agents,
        "framework_version": framework_version,
        "llm_provider": llm_provider,
        "llm_model": llm_model,
    })


@router.get("/agent/{name}", response_class=HTMLResponse)
async def agent_detail(request: Request, name: str):
    agent = get_agent(name)
    if not agent:
        return HTMLResponse("<h1>Agent not found</h1>", status_code=404)
    tab = request.query_params.get("tab", "overview")
    agents = list_agents()
    cfg = get_config()
    return _render("agent_detail.html", {
        "request": request,
        "agents": agents,
        "agent": agent,
        "tab": tab,
        "framework_version": cfg.get("framework", {}).get("version", "0.4.1"),
        "llm_provider": cfg.get("llm", {}).get("provider", "unknown"),
        "llm_model": cfg.get("llm", {}).get("model", "unknown"),
    })


@router.get("/settings", response_class=HTMLResponse)
async def settings_page(request: Request):
    cfg = get_config()
    agents = list_agents()
    return _render("settings.html", {
        "request": request,
        "agents": agents,
        "config": cfg,
        "framework_version": cfg.get("framework", {}).get("version", "0.4.1"),
        "llm_provider": cfg.get("llm", {}).get("provider", "unknown"),
        "llm_model": cfg.get("llm", {}).get("model", "unknown"),
    })


@router.get("/create", response_class=HTMLResponse)
async def create_agent_page(request: Request):
    agents = list_agents()
    cfg = get_config()
    return _render("create.html", {
        "request": request,
        "agents": agents,
        "framework_version": cfg.get("framework", {}).get("version", "0.4.1"),
        "llm_provider": cfg.get("llm", {}).get("provider", "unknown"),
        "llm_model": cfg.get("llm", {}).get("model", "unknown"),
    })


@router.get("/agent/{name}/tab/{tab}", response_class=HTMLResponse)
async def agent_tab(request: Request, name: str, tab: str):
    agent = get_agent(name)
    if not agent:
        return HTMLResponse("<p class='p-6 text-gray-400'>Agent not found.</p>", status_code=404)

    if tab == "overview":
        goals = get_agent_goals(name)
        decisions, _ = get_agent_decisions(name, limit=5)
        return _render("agent_tabs/overview.html", {
            "request": request, "agent": agent, "goals": goals, "recent_decisions": decisions,
        })
    elif tab == "chat":
        return _render("agent_tabs/chat.html", {
            "request": request, "agent": agent,
        })
    elif tab == "tools":
        tools = get_agent_tools(name)
        return _render("agent_tabs/tools.html", {
            "request": request, "agent": agent, "tools": tools,
        })
    elif tab == "evolution":
        events = get_agent_evolution(name)
        metrics = get_agent_metrics(name)
        return _render("agent_tabs/evolution.html", {
            "request": request, "agent": agent, "events": events, "metrics": metrics,
        })
    elif tab == "decisions":
        entries, total = get_agent_decisions(name, limit=20)
        return _render("agent_tabs/decisions.html", {
            "request": request, "agent": agent, "decisions": entries,
            "total": total, "limit": 20, "offset": 0,
        })
    elif tab == "personality":
        personality = get_agent_personality(name)
        return _render("agent_tabs/personality.html", {
            "request": request, "agent": agent, "personality": personality,
        })
    elif tab == "knowledge":
        files = get_agent_knowledge(name)
        return _render("agent_tabs/knowledge.html", {
            "request": request, "agent": agent, "files": files,
        })
    else:
        return HTMLResponse("<p class='p-6 text-gray-400'>Unknown tab.</p>", status_code=404)


@router.post("/agent/{name}/controls/start", response_class=HTMLResponse)
async def agent_control_start(request: Request, name: str):
    import subprocess, sys
    supervisor = str(Path(__file__).resolve().parent.parent.parent / "supervise_agent.py")
    subprocess.run(
        [sys.executable, supervisor, "--agent-name", name, "--daemon", "--"],
        capture_output=True, text=True,
    )
    import time
    time.sleep(0.5)
    agent = get_agent(name)
    return _render("components/agent_controls.html", {
        "request": request, "agent": agent or {"name": name, "status": "unknown"},
    })


@router.post("/agent/{name}/controls/stop", response_class=HTMLResponse)
async def agent_control_stop(request: Request, name: str):
    import subprocess, sys
    supervisor = str(Path(__file__).resolve().parent.parent.parent / "supervise_agent.py")
    subprocess.run(
        [sys.executable, supervisor, "--agent-name", name, "--stop"],
        capture_output=True, text=True,
    )
    import time
    time.sleep(0.5)
    agent = get_agent(name)
    return _render("components/agent_controls.html", {
        "request": request, "agent": agent or {"name": name, "status": "unknown"},
    })


@router.post("/agent/{name}/controls/restart", response_class=HTMLResponse)
async def agent_control_restart(request: Request, name: str):
    import subprocess, sys
    supervisor = str(Path(__file__).resolve().parent.parent.parent / "supervise_agent.py")
    subprocess.run(
        [sys.executable, supervisor, "--agent-name", name, "--stop"],
        capture_output=True, text=True,
    )
    import time
    time.sleep(1)
    subprocess.run(
        [sys.executable, supervisor, "--agent-name", name, "--daemon", "--"],
        capture_output=True, text=True,
    )
    time.sleep(0.5)
    agent = get_agent(name)
    return _render("components/agent_controls.html", {
        "request": request, "agent": agent or {"name": name, "status": "unknown"},
    })
