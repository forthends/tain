from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Optional


class PackageKind(str, Enum):
    AGENT = "agent"
    TOOLSET = "toolset"
    SKILL = "skill"


class LayerKind(str, Enum):
    INFRA = "infra"
    CAPABILITY = "capability"
    COGNITIVE = "cognitive"
    EXPRESSION = "expression"


# subdirectories within each layer for agent packages
LAYER_SUBDIRS: dict[LayerKind, list[str]] = {
    LayerKind.INFRA: [],
    LayerKind.CAPABILITY: ["tools", "skills", "tests"],
    LayerKind.COGNITIVE: ["knowledge", "memory", "identity"],
    LayerKind.EXPRESSION: ["artifacts"],
}

RUNTIME_DIR = "_runtime"
RUNTIME_SUBDIRS = ["state", "conversations", "cache", "locks"]


@dataclass
class AgentPackage:
    """First-class entity representing an Agent as a package."""
    name: str
    kind: PackageKind
    version: str
    packages_root: Path

    @property
    def path(self) -> Path:
        return self.packages_root / self.name

    @property
    def manifest_path(self) -> Path:
        return self.path / "manifest.json"

    @property
    def runtime_dir(self) -> Path:
        return self.path / RUNTIME_DIR

    def layer_dir(self, layer: LayerKind) -> Path:
        return self.path / layer.value

    def layer_dirs(self) -> dict[LayerKind, Path]:
        return {layer: self.layer_dir(layer) for layer in LayerKind}

    def ensure_directories(self) -> None:
        """Create all layer directories and runtime dirs."""
        for layer in LayerKind:
            layer_path = self.layer_dir(layer)
            layer_path.mkdir(parents=True, exist_ok=True)
            for sub in LAYER_SUBDIRS.get(layer, []):
                (layer_path / sub).mkdir(parents=True, exist_ok=True)
        for sub in RUNTIME_SUBDIRS:
            (self.runtime_dir / sub).mkdir(parents=True, exist_ok=True)
