"""Agent instance cache with mtime-based invalidation — AgentRuntime-based."""
import asyncio
import time
import logging
from pathlib import Path

import yaml
from tain_agent.package import PackageRegistry
from tain_agent.runtime import AgentRuntime

logger = logging.getLogger(__name__)

_PACKAGES_ROOT: Path = Path("agent_workspace/packages")
_runtime_cache: dict[str, tuple[float, "AgentRuntime"]] = {}
_build_locks: dict[str, asyncio.Lock] = {}


def _build_runtime(name: str, config_path: str) -> "AgentRuntime":
    """Build an AgentRuntime for a package."""
    reg = PackageRegistry(packages_root=_PACKAGES_ROOT)
    pkg = reg.get_package(name)
    if pkg is None:
        raise FileNotFoundError(f"Package not found: {name}")
    with open(config_path) as f:
        config = yaml.safe_load(f)
    return AgentRuntime(package=pkg, config=config)


def get_runtime(name: str, config_path: str) -> "AgentRuntime":
    """Get or create an AgentRuntime (sync, cached)."""
    now = time.time()
    if name in _runtime_cache:
        cached_time, runtime = _runtime_cache[name]
        pkg_path = _PACKAGES_ROOT / name / "manifest.json"
        if pkg_path.exists():
            mtime = pkg_path.stat().st_mtime
            if mtime <= cached_time:
                return runtime
    runtime = _build_runtime(name, config_path)
    _runtime_cache[name] = (now, runtime)
    return runtime


async def get_runtime_async(name: str, config_path: str) -> "AgentRuntime":
    """Get or create an AgentRuntime (async, cached)."""
    lock = _build_locks.setdefault(name, asyncio.Lock())
    async with lock:
        return get_runtime(name, config_path)


# Backward-compatible aliases
def get_agent(name: str, config_path: str) -> "AgentRuntime":
    """Deprecated alias — use get_runtime()."""
    return get_runtime(name, config_path)


def get_kernel(name: str, config_path: str) -> "AgentRuntime":
    """Deprecated alias — use get_runtime()."""
    return get_runtime(name, config_path)


async def get_agent_async(name: str, config_path: str) -> "AgentRuntime":
    """Deprecated alias — use get_runtime_async()."""
    return await get_runtime_async(name, config_path)


async def get_kernel_async(name: str, config_path: str) -> "AgentRuntime":
    """Deprecated alias — use get_runtime_async()."""
    return await get_runtime_async(name, config_path)


def invalidate_agent(name: str) -> bool:
    """Force-invalidate a cached agent."""
    if name in _runtime_cache:
        del _runtime_cache[name]
        logger.info("Agent %s manually invalidated", name)
        return True
    return False
