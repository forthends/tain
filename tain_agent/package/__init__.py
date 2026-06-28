from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Optional

from tain_agent.package.manifest import (
    Manifest, parse_manifest, create_manifest, ManifestValidationError,
)


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


class PackageRegistry:
    """Registry that scans packages/ directory for Agent packages.

    Scans packages/*/manifest.json to discover packages. manifest is the single
    source of truth — no separate _registry.json needed for package metadata.
    """

    def __init__(self, packages_root: Path):
        self._root = Path(packages_root)

    @property
    def packages_root(self) -> Path:
        return self._root

    def list_packages(self, kind: Optional[PackageKind] = None) -> list[AgentPackage]:
        """List all discovered packages, optionally filtered by kind."""
        if not self._root.exists():
            return []
        results = []
        for pkg_dir in sorted(self._root.iterdir()):
            if not pkg_dir.is_dir():
                continue
            manifest_path = pkg_dir / "manifest.json"
            if not manifest_path.exists():
                continue
            try:
                manifest = parse_manifest(manifest_path)
            except ManifestValidationError:
                continue
            if kind and manifest.package.kind != kind.value:
                continue
            results.append(AgentPackage(
                name=manifest.package.name,
                kind=PackageKind(manifest.package.kind),
                version=manifest.package.version,
                packages_root=self._root,
            ))
        return results

    def get_package(self, name: str) -> Optional[AgentPackage]:
        """Get a single package by name."""
        pkg = AgentPackage(name=name, kind=PackageKind.AGENT, version="", packages_root=self._root)
        if not pkg.manifest_path.exists():
            return None
        manifest = parse_manifest(pkg.manifest_path)
        return AgentPackage(
            name=manifest.package.name,
            kind=PackageKind(manifest.package.kind),
            version=manifest.package.version,
            packages_root=self._root,
        )

    def get_manifest(self, name: str) -> Optional[Manifest]:
        """Get parsed manifest for a package by name."""
        pkg = self.get_package(name)
        if pkg is None:
            return None
        return parse_manifest(pkg.manifest_path)

    def create(
        self,
        name: str,
        kind: PackageKind = PackageKind.AGENT,
        version: str = "0.0.0",
        evolution_mode: str = "chaos",
        plugins: dict[str, str] | None = None,
    ) -> AgentPackage:
        """Create a new package directory with a minimal manifest."""
        pkg = AgentPackage(name=name, kind=kind, version=version, packages_root=self._root)
        if pkg.path.exists():
            raise FileExistsError(f"Package already exists: {pkg.path}")
        pkg.ensure_directories()
        manifest = create_manifest(
            name=name, kind=kind.value, version=version,
            evolution_mode=evolution_mode, plugins=plugins,
        )
        manifest.to_json(pkg.manifest_path)
        return pkg

    def validate(self, name: str) -> tuple[bool, list[str]]:
        """Validate a package: manifest exists, valid, hashes match. Returns (ok, errors)."""
        errors = []
        pkg = self.get_package(name)
        if pkg is None:
            return False, [f"Package not found: {name}"]
        try:
            manifest = parse_manifest(pkg.manifest_path)
        except ManifestValidationError as e:
            return False, [str(e)]
        hash_errors = manifest.verify_hashes(pkg.path)
        errors.extend(hash_errors)
        return len(errors) == 0, errors


def bump_version(current: str, layer: str | LayerKind) -> str:
    """Bump semver according to evolution layer rules.

    expression → PATCH
    capability, cognitive, cognitive/identity → MINOR
    infra → MAJOR
    """
    layer_str = layer.value if isinstance(layer, LayerKind) else layer
    parts = [int(p) for p in current.split(".")]
    if len(parts) != 3:
        raise ValueError(f"Invalid semver: {current}")
    major, minor, patch = parts

    if layer_str in ("infra",):
        return f"{major + 1}.0.0"
    elif layer_str in ("capability", "cognitive", "cognitive/identity"):
        return f"{major}.{minor + 1}.0"
    else:
        return f"{major}.{minor}.{patch + 1}"
