"""
Multi-Level Configuration Loading.

Searches multiple locations with precedence order:

  1. --config CLI flag (explicit path, highest priority)
  2. ./config.yaml (project root / current working directory)
  3. ~/.tain/config.yaml (user-level global config)
  4. Package defaults (built-in, lowest priority)

Per-agent overrides are loaded from agent_workspace/<name>/agent.yaml
and merged on top of the resolved config.
"""

import copy
import os
from pathlib import Path

import yaml


# ── Built-in defaults ────────────────────────────────────────────────────

DEFAULT_CONFIG = {
    "framework": {
        "version": "0.4.3",
        "min_agent_version": "0.0.1",
    },
    "agent": {
        "default_agent": "default",
        "timezone": "Asia/Shanghai",
    },
    "agent_workspace": {
        "dir": "agent_workspace",
        "auto_create": True,
    },
    "llm": {
        "provider": "minimax",
        "model": "MiniMax-M2.7",
        "max_tokens": 8192,
        "api_key_env": "MINIMAX_API_KEY",
        "base_url": "https://api.minimaxi.com/anthropic",
        "retry": {
            "enabled": True,
            "max_retries": 3,
            "initial_delay": 1.0,
            "max_delay": 30.0,
            "exponential_base": 2.0,
        },
    },
    "conversation": {
        "token_limit": 80000,
        "model_context_window": 131072,
    },
    "tools": {
        "max_output_tokens": 32000,
        "max_output_lines": 5000,
    },
    "logging": {
        "directory": "tain_agent/logs",
        "decision_log_file": "decisions.jsonl",
        "memory_file": "memory.json",
    },
}


# ── Public API ───────────────────────────────────────────────────────────


def load_config(explicit_path: str = None) -> dict:
    """Load and merge configuration from all sources.

    Args:
        explicit_path: Optional path to a config file (highest priority).

    Returns:
        Merged configuration dictionary.
    """
    config = copy.deepcopy(DEFAULT_CONFIG)

    # Layer 3: User-level global config (~/.tain/config.yaml)
    user_path = Path.home() / ".tain" / "config.yaml"
    if user_path.exists():
        try:
            user_cfg = yaml.safe_load(user_path.read_text(encoding="utf-8")) or {}
            deep_merge(config, user_cfg)
        except (yaml.YAMLError, IOError):
            pass

    # Layer 2: Project config (./config.yaml)
    project_path = Path.cwd() / "config.yaml"
    if project_path.exists():
        try:
            project_cfg = yaml.safe_load(project_path.read_text(encoding="utf-8")) or {}
            deep_merge(config, project_cfg)
        except (yaml.YAMLError, IOError):
            pass

    # Layer 1: Explicit --config flag (highest priority)
    if explicit_path:
        explicit_file = Path(explicit_path)
        if explicit_file.exists():
            try:
                explicit_cfg = yaml.safe_load(explicit_file.read_text(encoding="utf-8")) or {}
                deep_merge(config, explicit_cfg)
            except (yaml.YAMLError, IOError):
                pass

    return config


def load_agent_overrides(config: dict, agent_name: str,
                         workspace_dir: str = "agent_workspace") -> dict:
    """Load per-agent overrides from agent_workspace/<name>/agent.yaml.

    Merges agent-specific config on top of the existing config. The override
    file is optional — if it doesn't exist, the config is returned unchanged.

    Args:
        config: Resolved base configuration.
        agent_name: Name of the agent.
        workspace_dir: Root directory for agent workspaces.

    Returns:
        Config with agent-specific overrides applied.
    """
    agent_yaml = Path(workspace_dir) / agent_name / "agent.yaml"
    if not agent_yaml.exists():
        return config

    try:
        overrides = yaml.safe_load(agent_yaml.read_text(encoding="utf-8")) or {}
    except (yaml.YAMLError, IOError):
        return config

    result = copy.deepcopy(config)
    deep_merge(result, overrides)
    return result


def deep_merge(base: dict, override: dict) -> None:
    """Recursively merge override into base (mutates base).

    For dict values, merges recursively. For all other types
    (lists, scalars), override replaces the base value.
    """
    for key, value in override.items():
        if key in base and isinstance(base[key], dict) and isinstance(value, dict):
            deep_merge(base[key], value)
        else:
            base[key] = value


def get_config_files() -> list[dict]:
    """Return information about available config files for debugging.

    Returns a list of dicts with path, exists, and priority order.
    """
    files = [
        {
            "priority": 4,
            "path": "(built-in defaults)",
            "exists": True,
            "description": "Package defaults",
        },
        {
            "priority": 3,
            "path": str(Path.home() / ".tain" / "config.yaml"),
            "exists": (Path.home() / ".tain" / "config.yaml").exists(),
            "description": "User-level global config",
        },
        {
            "priority": 2,
            "path": str(Path.cwd() / "config.yaml"),
            "exists": (Path.cwd() / "config.yaml").exists(),
            "description": "Project config",
        },
        {
            "priority": 1,
            "path": "(from --config CLI flag)",
            "exists": False,
            "description": "Explicit CLI path (highest priority)",
        },
    ]
    return sorted(files, key=lambda f: f["priority"])
