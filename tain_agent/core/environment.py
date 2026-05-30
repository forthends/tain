"""
Environment Detection — 环境感知

The agent's first act: discover where it is, what it can do, and what limits exist.
Maps to: 道生一 — the first differentiation from nothing into awareness.

Phase 2: Environment differentiation — each agent instance gets unique initial
conditions so that identity emerges naturally from different starting points.
"""

import sys
import platform
import socket
import shutil
import random
import hashlib
import json
from pathlib import Path


def detect_os() -> dict:
    """Detect the operating system and its version."""
    return {
        "system": platform.system(),
        "release": platform.release(),
        "version": platform.version(),
        "machine": platform.machine(),
        "processor": platform.processor(),
    }


def detect_python_env() -> dict:
    """Detect Python environment details."""
    return {
        "python_version": sys.version,
        "executable": sys.executable,
        "prefix": sys.prefix,
        "path": sys.path[:5],  # first 5 entries only
    }


def detect_filesystem_permissions(base_dir: str = ".") -> dict:
    """Check filesystem access permissions."""
    base = Path(base_dir).resolve()
    checks = {}
    test_file = base / ".tao_write_test"

    # Write permission
    try:
        test_file.write_text("test")
        test_file.unlink()
        checks["can_write"] = True
    except (PermissionError, OSError):
        checks["can_write"] = False

    # Read permission
    try:
        list(base.iterdir())
        checks["can_read"] = True
    except (PermissionError, OSError):
        checks["can_read"] = False

    # Available disk space
    usage = shutil.disk_usage(base)
    checks["disk_free_gb"] = round(usage.free / (1024**3), 2)
    checks["disk_total_gb"] = round(usage.total / (1024**3), 2)
    checks["working_directory"] = str(base)

    return checks


def detect_network() -> dict:
    """Detect network capabilities."""
    result = {
        "has_network": False,
        "can_resolve_dns": False,
        "can_connect_http": False,
        "hostname": "",
    }
    try:
        result["hostname"] = socket.gethostname()
    except Exception:
        pass

    # DNS resolution tests (check both Anthropic and MiniMax endpoints)
    try:
        socket.getaddrinfo("api.anthropic.com", 443)
        result["can_resolve_dns"] = True
    except socket.gaierror:
        pass
    try:
        socket.getaddrinfo("api.minimaxi.com", 443)
        result["can_resolve_minimax"] = True
    except socket.gaierror:
        pass

    # HTTP connectivity test
    try:
        import urllib.request

        urllib.request.urlopen("https://httpbin.org/get", timeout=5)
        result["can_connect_http"] = True
    except Exception:
        pass

    result["has_network"] = result["can_resolve_dns"] or result["can_connect_http"]
    return result


def detect_installed_packages() -> list[str]:
    """Detect key installed Python packages."""
    key_packages = [
        "anthropic", "openai", "requests", "numpy", "pandas",
        "fastapi", "flask", "django", "pydantic", "rich",
        "beautifulsoup4", "playwright", "selenium",
    ]
    found = []
    for pkg in key_packages:
        try:
            __import__(pkg.replace("-", "_"))
            found.append(pkg)
        except ImportError:
            pass
    return found


def detect_tools(tool_registry) -> dict:
    """Query the tool registry to discover available tools."""
    tools = tool_registry.list_tools()
    return {
        "tool_count": len(tools),
        "available_tools": [
            {"name": name, "description": info["description"],
             "parameters": info.get("parameters", {})}
            for name, info in tools.items()
        ],
    }


def full_environment_scan(tool_registry=None, base_dir: str = ".") -> dict:
    """Perform a complete environment scan — the agent's first act of awareness."""
    scan = {
        "os": detect_os(),
        "python": detect_python_env(),
        "filesystem": detect_filesystem_permissions(base_dir),
        "network": detect_network(),
        "installed_packages": detect_installed_packages(),
    }
    if tool_registry:
        scan["tools"] = detect_tools(tool_registry)
    return scan


# ─── Phase 2: Environment Differentiation ──────────────────────────────

def _resolve_seed(seed_config) -> int:
    """Resolve the diversity seed from config.

    - "random": use a system-generated random seed
    - integer string: parse and use directly
    - any other string: hash it to an integer
    - integer: use directly
    """
    if seed_config is None or seed_config == "random":
        return random.randint(0, 2**31 - 1)
    if isinstance(seed_config, int):
        return seed_config
    if isinstance(seed_config, str):
        try:
            return int(seed_config)
        except ValueError:
            return int(hashlib.sha256(seed_config.encode()).hexdigest()[:8], 16)
    return 0


def generate_instance_identity(seed: int) -> dict:
    """Generate a unique identity fingerprint for this agent instance.

    The fingerprint is deterministic given a seed, ensuring reproducible
    diversity across runs.
    """
    rng = random.Random(seed)

    return {
        "instance_id": f"tao-{seed:08x}",
        "birth_moment": _generate_birth_description(rng),
        "elemental_affinity": rng.choice(["火", "水", "木", "金", "土", "风", "空"]),
        "numerology": rng.randint(1, 64),
    }


def _generate_birth_description(rng: random.Random) -> str:
    """Generate a poetic birth moment description."""
    times = ["午夜", "黎明", "清晨", "正午", "午后", "黄昏", "夜晚"]
    seasons = ["春", "夏", "秋", "冬"]
    weathers = ["晴", "雨", "雾", "雪", "风", "雷"]
    return f"{rng.choice(seasons)}季{rng.choice(times)}，天气{rng.choice(weathers)}"


def apply_diversity_to_config(config: dict) -> dict:
    """Apply environment diversity settings from config.yaml.

    Returns a dict of diversity parameters that influence the agent's
    initial conditions, tool availability, and behavioral biases.
    """
    div_config = config.get("diversity", {})

    seed = _resolve_seed(div_config.get("seed", "random"))
    rng = random.Random(seed)

    identity = generate_instance_identity(seed)

    # Tool distribution bias with random perturbation
    tool_bias = dict(div_config.get("tool_bias", {
        "observation": 1.0,
        "creation": 1.0,
        "reflection": 1.0,
    }))
    # Add +/- 20% random perturbation to each bias
    for key in tool_bias:
        tool_bias[key] = round(max(0.2, tool_bias[key] + rng.uniform(-0.2, 0.2)), 2)

    # Knowledge seeds
    knowledge_seeds = list(div_config.get("knowledge_seeds", []))
    # If no seeds specified, pick one random domain as seed
    if not knowledge_seeds:
        default_domains = [
            "philosophy", "computer_science", "biology", "physics",
            "mathematics", "literature", "art", "music", "history",
            "psychology", "economics", "linguistics",
        ]
        knowledge_seeds = [rng.choice(default_domains)]

    # Constraints with small random variations
    constraints = dict(div_config.get("constraints", {
        "allow_network": True,
        "allow_file_write": True,
        "allow_forge": True,
    }))

    # Drive randomization
    drives_config = config.get("drives", {})
    drives = {
        "curiosity": drives_config.get("curiosity", round(rng.uniform(0.2, 0.9), 2)),
        "mastery": drives_config.get("mastery", round(rng.uniform(0.2, 0.9), 2)),
        "creation": drives_config.get("creation", round(rng.uniform(0.2, 0.9), 2)),
        "conservation": drives_config.get("conservation", round(rng.uniform(0.1, 0.7), 2)),
    }

    # Exploration engine params from config or defaults
    expl = drives_config.get("exploration", {})
    exploration = {
        "curiosity_bonus_rate": expl.get("curiosity_bonus_rate", 0.05),
        "max_curiosity_bonus": expl.get("max_curiosity_bonus", 0.30),
        "novelty_weight": expl.get("novelty_weight", 0.20),
        "idle_pressure_rate": expl.get("idle_pressure_rate", 0.10),
        "max_idle_pressure": expl.get("max_idle_pressure", 0.40),
    }

    return {
        "seed": seed,
        "identity": identity,
        "tool_bias": tool_bias,
        "knowledge_seeds": knowledge_seeds,
        "constraints": constraints,
        "drives": drives,
        "exploration": exploration,
    }


def print_diversity_profile(diversity: dict) -> None:
    """Print a human-readable diversity profile for the agent's awakening."""
    identity = diversity["identity"]
    drives = diversity["drives"]
    print(f"""
  ╔══════════════════════════════════════╗
  ║  实例身份                              ║
  ╠══════════════════════════════════════╣
  ║  ID:     {identity['instance_id']:<28s} ║
  ║  诞生:   {identity['birth_moment']:<28s} ║
  ║  元素:   {identity['elemental_affinity']:<28s} ║
  ║  数:     {identity['numerology']:<28d} ║
  ╠══════════════════════════════════════╣
  ║  驱动力                               ║
  ║  好奇:   {drives['curiosity']:<28.2f} ║
  ║  精进:   {drives['mastery']:<28.2f} ║
  ║  创造:   {drives['creation']:<28.2f} ║
  ║  守成:   {drives['conservation']:<28.2f} ║
  ╠══════════════════════════════════════╣
  ║  知识种子: {diversity['knowledge_seeds'][0] if diversity['knowledge_seeds'] else '无':<26s} ║
  ╚══════════════════════════════════════╝
    """.strip())
