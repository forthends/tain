"""Page routes — return HTML."""

import asyncio
import json as _json
import os
import time
from datetime import datetime as _datetime
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, StreamingResponse
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
    framework_version = cfg.get("framework", {}).get("version", "0.4.3")
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
        "framework_version": cfg.get("framework", {}).get("version", "0.4.3"),
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
        "framework_version": cfg.get("framework", {}).get("version", "0.4.3"),
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
        "framework_version": cfg.get("framework", {}).get("version", "0.4.3"),
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
        cfg = get_config()
        return _render("agent_tabs/chat.html", {
            "request": request, "agent": agent,
            "llm_provider": cfg.get("llm", {}).get("provider", "unknown"),
            "llm_model": cfg.get("llm", {}).get("model", "unknown"),
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
    elif tab == "live":
        return _render("agent_tabs/live.html", {
            "request": request, "agent": agent,
        })
    else:
        return HTMLResponse("<p class='p-6 text-gray-400'>Unknown tab.</p>", status_code=404)


@router.get("/agent/{name}/decisions-list", response_class=HTMLResponse)
async def agent_decisions_list(name: str, phase: str = "", type: str = "",
                                limit: int = 20, offset: int = 0):
    agent = get_agent(name)
    entries, total = get_agent_decisions(name, phase=phase, decision_type=type,
                                          limit=limit, offset=offset)

    if offset > 0:
        # Load More: append cards + OOB update summary & button
        cards = _jinja_env.get_template("components/decision_entry.html")
        cards_html = cards.render(decisions=entries)

        remaining = total - offset - len(entries)
        btn = ""
        if remaining > 0:
            new_offset = offset + limit
            btn = (
                f'<button id="load-more-btn" hx-swap-oob="true"'
                f' hx-get="/agent/{name}/decisions-list?limit={limit}&offset={new_offset}&phase={phase}&type={type}"'
                f' hx-target="#decisions-list" hx-swap="beforeend"'
                f' class="mt-3 text-sm text-blue-500 hover:text-blue-600">'
                f'Load More...</button>'
            )
        else:
            btn = '<span id="load-more-btn" hx-swap-oob="true"></span>'

        summary = (
            f'<p id="decisions-summary" hx-swap-oob="true" class="text-xs text-gray-400 mb-3">'
            f'Showing {offset + len(entries)} of {total} decisions</p>'
        )
        return HTMLResponse(cards_html + summary + btn)

    # Filter/reset: replace entire content
    tmpl = _jinja_env.get_template("components/decisions_list.html")
    html = tmpl.render(agent=agent, decisions=entries,
                       total=total, limit=limit, offset=offset,
                       phase=phase, type=type)
    return HTMLResponse(html)


@router.get("/agent/{name}/knowledge/render", response_class=HTMLResponse)
async def agent_knowledge_render(name: str, path: str):
    from webui.data import get_agent_knowledge_content
    from webui.render import render_content
    fmt, content = get_agent_knowledge_content(name, path)
    html = render_content(content, fmt)
    filename = path.split("/")[-1]
    return _render("components/knowledge_viewer.html", {
        "filename": filename, "format": fmt, "html": html,
    })


@router.get("/sidebar/agents", response_class=HTMLResponse)
async def sidebar_agents(request: Request):
    current = request.query_params.get("current", "")
    agents = list_agents()
    return _render("components/sidebar_agents.html", {
        "request": request, "agents": agents, "current_agent": current,
    })


_LOG_DIR = Path(__file__).resolve().parent.parent.parent / "tain_agent" / "logs"


def _log_path_for(agent_name: str) -> Path:
    return _LOG_DIR / f"agent_output_{agent_name}.log"


async def _tail_log(agent_name: str):
    """SSE generator that tails a per-agent output log, sending JSON events."""
    path = _log_path_for(agent_name)
    # Wait for the log file to appear (agent may not have started yet)
    while not path.exists():
        await asyncio.sleep(1)
    with open(path, "r") as f:
        f.seek(0, os.SEEK_END)
        while True:
            line = f.readline()
            if line:
                ts = _datetime.now().strftime("%H:%M:%S")
                payload = _json.dumps({"text": line.rstrip("\n"), "timestamp": ts})
                yield f"data: {payload}\n\n"
            else:
                await asyncio.sleep(0.5)


@router.get("/stream/agent-output")
async def stream_agent_output(agent: str = ""):
    """Server-Sent Events endpoint streaming per-agent output log."""
    if agent:
        return StreamingResponse(
            _tail_log(agent),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )
    # Legacy fallback: stream shared log for clients without agent param
    shared = _LOG_DIR / "agent_output.log"
    return StreamingResponse(
        _tail_log_shared(shared),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


async def _tail_log_shared(path: Path):
    """Fallback SSE generator for the legacy shared log."""
    if path.exists():
        with open(path, "r") as f:
            f.seek(0, os.SEEK_END)
            while True:
                line = f.readline()
                if line:
                    ts = _datetime.now().strftime("%H:%M:%S")
                    payload = _json.dumps({"text": line.rstrip("\n"), "timestamp": ts})
                    yield f"data: {payload}\n\n"
                else:
                    await asyncio.sleep(0.5)


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
    resp = _render("components/agent_controls.html", {
        "request": request, "agent": agent or {"name": name, "status": "unknown"},
    })
    resp.headers["HX-Trigger"] = "agentStatusChanged"
    return resp


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
    resp = _render("components/agent_controls.html", {
        "request": request, "agent": agent or {"name": name, "status": "unknown"},
    })
    resp.headers["HX-Trigger"] = "agentStatusChanged"
    return resp


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
    resp = _render("components/agent_controls.html", {
        "request": request, "agent": agent or {"name": name, "status": "unknown"},
    })
    resp.headers["HX-Trigger"] = "agentStatusChanged"
    return resp
