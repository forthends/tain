# tain_agent/package/cli.py
"""CLI command handlers for tain package subcommands."""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Optional

from tain_agent.package import AgentPackage, PackageKind, PackageRegistry
from tain_agent.package.manifest import (
    Manifest, parse_manifest, create_manifest,
)

DEFAULT_PACKAGES_ROOT = Path("agent_workspace/packages")


def cmd_package_create(
    name: str,
    kind: str = "agent",
    version: str = "0.0.0",
    evolution_mode: str = "chaos",
    plugins: Optional[dict[str, str]] = None,
    packages_root: Optional[Path] = None,
) -> dict:
    """Create a new agent package."""
    root = Path(packages_root) if packages_root else DEFAULT_PACKAGES_ROOT
    reg = PackageRegistry(packages_root=root)
    try:
        pkg = reg.create(
            name=name,
            kind=PackageKind(kind),
            version=version,
            evolution_mode=evolution_mode,
            plugins=plugins or {},
        )
        return {"ok": True, "package": {"name": pkg.name, "path": str(pkg.path), "version": pkg.version}}
    except FileExistsError as e:
        return {"ok": False, "error": str(e)}


def cmd_package_validate(name: str, packages_root: Optional[Path] = None) -> dict:
    """Validate a package's manifest and file hashes."""
    root = Path(packages_root) if packages_root else DEFAULT_PACKAGES_ROOT
    reg = PackageRegistry(packages_root=root)
    ok, errors = reg.validate(name)
    return {"ok": ok, "errors": errors}


def cmd_package_list(
    kind: Optional[str] = None,
    packages_root: Optional[Path] = None,
) -> dict:
    """List discovered packages."""
    root = Path(packages_root) if packages_root else DEFAULT_PACKAGES_ROOT
    reg = PackageRegistry(packages_root=root)
    pkg_kind = PackageKind(kind) if kind else None
    pkgs = reg.list_packages(kind=pkg_kind)
    return {
        "ok": True,
        "packages": [{"name": p.name, "kind": p.kind.value, "version": p.version, "path": str(p.path)} for p in pkgs],
    }


def cmd_package_export(name: str, output: Path, packages_root: Optional[Path] = None) -> dict:
    """Export a package by copying it (excluding _runtime/) to output dir."""
    root = Path(packages_root) if packages_root else DEFAULT_PACKAGES_ROOT
    reg = PackageRegistry(packages_root=root)
    pkg = reg.get_package(name)
    if pkg is None:
        return {"ok": False, "error": f"Package not found: {name}"}
    dest = Path(output) / name
    if dest.exists():
        shutil.rmtree(dest)

    def _ignore_runtime(directory, contents):
        return {"_runtime"} if "_runtime" in contents else set()

    shutil.copytree(pkg.path, dest, ignore=_ignore_runtime)
    return {"ok": True, "path": str(dest)}


def cmd_package_import(source: Path, packages_root: Optional[Path] = None) -> dict:
    """Import a package by copying it into packages/."""
    root = Path(packages_root) if packages_root else DEFAULT_PACKAGES_ROOT
    source = Path(source)
    if not source.exists():
        return {"ok": False, "error": f"Source not found: {source}"}
    manifest_path = source / "manifest.json"
    if not manifest_path.exists():
        return {"ok": False, "error": "Source does not contain manifest.json"}
    manifest = parse_manifest(manifest_path)
    name = manifest.package.name
    dest = root / name
    if dest.exists():
        return {"ok": False, "error": f"Package '{name}' already exists in packages/"}
    root.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source, dest)
    return {"ok": True, "path": str(dest)}
