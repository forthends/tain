"""Agent instance cache with mtime-based invalidation."""
import time
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

_cache: dict[str, tuple[float, "TaoAgent"]] = {}
WORKSPACE_ROOT: Path = Path("agent_workspace")


def get_agent(name: str, config_path: str) -> "TaoAgent":
    """Get or create a cached agent instance. Rebuilds if config changed."""
    from tain_agent.core.agent import TaoAgent

    global WORKSPACE_ROOT
    workspace = WORKSPACE_ROOT / name
    mtime = 0.0

    for path in (workspace / "agent.yaml", workspace / "version.json"):
        if path.exists():
            mtime = max(mtime, path.stat().st_mtime)

    if name in _cache:
        cached_mtime, agent = _cache[name]
        if cached_mtime >= mtime:
            return agent
        logger.info("Agent %s cache invalidated", name)

    logger.info("Creating new agent instance for %s", name)
    agent = TaoAgent(config_path=config_path, agent_name=name)
    _cache[name] = (time.time(), agent)
    return agent


def invalidate_agent(name: str) -> bool:
    """Force-invalidate a cached agent. Returns True if was cached."""
    if name in _cache:
        del _cache[name]
        logger.info("Agent %s manually invalidated", name)
        return True
    return False
