# tain_agent/runtime/plugin_loader.py
"""Dynamic plugin assembly driven by manifest declarations."""

from __future__ import annotations

import re
from typing import Any


class PluginVersionError(Exception):
    def __init__(self, plugin_name: str, requested: str, available: str):
        super().__init__(
            f"Plugin '{plugin_name}': requested {requested}, available {available}"
        )
        self.plugin_name = plugin_name
        self.requested = requested
        self.available = available


def semver_match(available: str, spec: str) -> bool:
    """Simple semver matching without external dependencies.

    Supports: exact match (1.2.0), caret (^1.2.0 → >=1.2.0,<2.0.0),
    tilde (~1.2.0 → >=1.2.0,<1.3.0).
    """
    avail_parts = [int(p) for p in available.split(".")]
    if len(avail_parts) != 3:
        return False

    if spec.startswith("^"):
        spec_parts = [int(p) for p in spec[1:].split(".")]
        if len(spec_parts) != 3:
            return False
        return (
            avail_parts[0] == spec_parts[0]
            and (avail_parts[0] > spec_parts[0] or avail_parts[1] >= spec_parts[1])
        )
    elif spec.startswith("~"):
        spec_parts = [int(p) for p in spec[1:].split(".")]
        if len(spec_parts) != 3:
            return False
        return (
            avail_parts[0] == spec_parts[0]
            and avail_parts[1] == spec_parts[1]
            and avail_parts[2] >= spec_parts[2]
        )
    else:
        # exact match
        spec_parts = [int(p) for p in spec.split(".")]
        return avail_parts == spec_parts


class PluginLoader:
    """Loads plugins based on manifest declarations.

    Perpetual plugins (identity, memory) are always loaded.
    Other plugins are loaded only if declared in the manifest.
    """

    PERPETUAL = frozenset({"identity", "memory"})

    def __init__(self, registry: dict[str, type] | None = None):
        self._registry = registry or {}

    @property
    def registry(self) -> dict[str, type]:
        return self._registry

    def assemble(self, manifest_plugins: dict[str, str], ctx: Any) -> list[Any]:
        """Assemble plugin instances from manifest declarations.

        Args:
            manifest_plugins: Dict from manifest.infra.plugins {"tool": "^1.2.0", ...}
            ctx: AgentContext for plugin initialization

        Returns:
            List of initialized plugin instances.
        """
        instances = []

        # 1. Always load perpetual plugins
        for name, cls in self._registry.items():
            if name in self.PERPETUAL:
                instance = cls()
                instance.initialize(ctx)
                instances.append(instance)

        # 2. Load plugins declared in manifest
        for name, version_spec in manifest_plugins.items():
            if name in self.PERPETUAL:
                continue
            if name not in self._registry:
                raise KeyError(f"Unknown plugin: {name}")
            cls = self._registry[name]
            if not semver_match(cls.version, version_spec):
                raise PluginVersionError(name, version_spec, cls.version)
            instance = cls()
            instance.initialize(ctx)
            instances.append(instance)

        return instances
