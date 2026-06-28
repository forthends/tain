"""Agent instance cache with mtime-based invalidation."""
import asyncio
import time
import logging
from pathlib import Path

import yaml
from tain_agent.kernel import AgentKernel, AgentContext, STANDARD_FACTORIES
from tain_agent import __version__

logger = logging.getLogger(__name__)

_cache: dict[str, tuple[float, "AgentKernel"]] = {}
_build_locks: dict[str, asyncio.Lock] = {}
WORKSPACE_ROOT: Path = Path("agent_workspace")


def _build_kernel(name: str, config_path: str) -> "AgentKernel":
    """Create an AgentKernel from a config file path."""
    with open(config_path) as f:
        config = yaml.safe_load(f)

    evolution_mode = config.get("agent", {}).get("evolution_mode", "specified")
    workspace = WORKSPACE_ROOT / name

    ctx = AgentContext(
        agent_name=name,
        agent_id=f"{name}-{workspace.name}",
        evolution_mode=evolution_mode,
        workspace_path=workspace,
        config=config,
        kernel_version=__version__,
    )
    kernel = AgentKernel(ctx)
    kernel.load_plugins(STANDARD_FACTORIES)
    return kernel


def get_agent(name: str, config_path: str) -> "AgentKernel":
    """Get or create a cached AgentKernel instance. Rebuilds if config changed."""
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
    kernel = _build_kernel(name, config_path)
    _cache[name] = (time.time(), kernel)
    return kernel


def get_kernel(name: str, config_path: str) -> "AgentKernel":
    """Alias for get_agent returning an AgentKernel."""
    return get_agent(name, config_path)


async def get_agent_async(name: str, config_path: str) -> "AgentKernel":
    """Async variant of get_agent with per-agent locking to prevent races.

    Two concurrent requests for the same uncached agent will share a single
    build — the second waits for the first to complete and then reuses its
    result.  Also offloads the synchronous _build_kernel to a thread so the
    event loop stays free.
    """
    global WORKSPACE_ROOT
    workspace = WORKSPACE_ROOT / name
    mtime = 0.0

    for path in (workspace / "agent.yaml", workspace / "version.json"):
        if path.exists():
            mtime = max(mtime, path.stat().st_mtime)

    # Fast path — cache hit (no lock needed for reads in single-threaded asyncio)
    if name in _cache:
        cached_mtime, agent = _cache[name]
        if cached_mtime >= mtime:
            return agent
        logger.info("Agent %s cache invalidated (mtime changed)", name)

    # Ensure a per-agent lock exists
    if name not in _build_locks:
        _build_locks[name] = asyncio.Lock()

    async with _build_locks[name]:
        # Double-check after acquiring the lock — another coroutine may have
        # finished building while we were waiting.
        if name in _cache:
            cached_mtime, agent = _cache[name]
            if cached_mtime >= mtime:
                return agent

        logger.info("Creating new agent instance for %s", name)
        kernel = await asyncio.to_thread(_build_kernel, name, config_path)
        _cache[name] = (time.time(), kernel)
        # Clean up the lock so the dict doesn't grow unbounded
        _build_locks.pop(name, None)
        return kernel


async def get_kernel_async(name: str, config_path: str) -> "AgentKernel":
    """Async alias for get_agent returning an AgentKernel."""
    return await get_agent_async(name, config_path)


def invalidate_agent(name: str) -> bool:
    """Force-invalidate a cached agent. Returns True if was cached."""
    if name in _cache:
        del _cache[name]
        logger.info("Agent %s manually invalidated", name)
        return True
    return False


# webui/agent_cache.py — AgentRuntime cache for v2 packages
from pathlib import Path as _Path
from tain_agent.package import PackageRegistry, AgentPackage as AgentPkg
from tain_agent.runtime import AgentRuntime

_PACKAGES_ROOT = _Path("agent_workspace/packages")

_runtime_cache: dict[str, tuple[float, "AgentRuntime"]] = {}


def _build_runtime(name: str, config_path: str) -> "AgentRuntime":
    """Build an AgentRuntime for a v2 package."""
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
