from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Optional

from tain_agent.package.manifest import (
    Manifest, parse_manifest, create_manifest, ManifestValidationError,
    PackageIntegrityError,
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

    # Internal cache (not an init parameter)
    _lineage: object | None = field(default=None, repr=False, init=False)

    @property
    def path(self) -> Path:
        return self.packages_root / self.name

    @property
    def manifest_path(self) -> Path:
        return self.path / "manifest.json"

    @property
    def runtime_dir(self) -> Path:
        return self.path / RUNTIME_DIR

    @property
    def lineage(self):
        """Lazy-loaded LineageTracker for this package."""
        if self._lineage is None:
            from tain_agent.evolution.lineage import LineageTracker
            lineage_path = self.path / "expression" / "lineage.jsonl"
            self._lineage = LineageTracker(lineage_path=lineage_path)
        return self._lineage

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

    # ── Evolution methods ──

    def apply_mutation(self, mutation) -> None:
        """Atomically apply a mutation to this package.

        1. Write all files to a temp dir
        2. Verify all writes succeeded
        3. Rename into place
        4. Update manifest
        5. Bump version
        6. Record lineage
        """
        import shutil
        import json
        from tain_agent.package.evolution import Mutation

        tmp_dir = self.path / "_mutation_tmp"
        tmp_dir.mkdir(exist_ok=True)

        try:
            # Stage 1: Write all files to temp dir
            written = []
            for rel_path, content_bytes in mutation.files_to_write:
                dest = tmp_dir / rel_path
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(content_bytes)
                written.append((rel_path, dest))

            # Stage 2: All succeeded — rename into place
            for rel_path, tmp_file in written:
                final = self.path / rel_path
                final.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(tmp_file), str(final))

            # Stage 3: Update manifest
            if mutation.manifest_patch:
                current_manifest = json.loads(self.manifest_path.read_text())
                _deep_merge(current_manifest, mutation.manifest_patch)
                self.manifest_path.write_text(
                    json.dumps(current_manifest, indent=2, ensure_ascii=False)
                )

            # Stage 4: Bump version
            new_version = bump_version(self.version, mutation.layer)
            _update_manifest_version(self.manifest_path, new_version)
            self.version = new_version

            # Stage 5: Record lineage
            self.lineage.record_mutation(
                version=new_version,
                layer=mutation.layer.value,
                change_type=mutation.change_type,
                detail=mutation.detail,
            )
        except Exception:
            raise
        finally:
            if tmp_dir.exists():
                shutil.rmtree(tmp_dir)

    def rollback_mutation(self, mutation) -> None:
        """Roll back a previously applied mutation.

        Removes files written by the mutation and records a rollback event.
        """
        # Remove files
        for rel_path, _content_bytes in mutation.files_to_write:
            file_path = self.path / rel_path
            if file_path.exists():
                file_path.unlink()

        # Record rollback lineage event
        self.lineage.record_rollback(
            version=self.version,
            reason=f"Quality gate failed for {mutation.change_type}: {mutation.detail}",
        )

    def evolve(
        self,
        gap_detector,
        mutation_generator,
        contract_checker,
        online_verifier,
    ):
        """Run one complete 5-stage evolution cycle.

        gap_detector(package) -> dict | None
        mutation_generator(gap, package) -> Mutation
        contract_checker(mutation, package) -> (bool, list[str])
        online_verifier(mutation, package) -> (bool, list[str])
        """
        from tain_agent.package.evolution import EvolutionResult

        # Stage 1: DETECT_GAP
        gap = gap_detector(self)
        if gap is None:
            return EvolutionResult.no_gap(self.version)

        # Stage 2: GENERATE_MUTATION
        mutation = mutation_generator(gap, self)

        # Stage 3: CONTRACT_CHECK
        ok, errors = contract_checker(mutation, self)
        if not ok:
            return EvolutionResult.contract_failed(self.version, mutation, errors)

        # Stage 4: WRITE_PACKAGE
        version_before = self.version
        try:
            self.apply_mutation(mutation)
        except Exception as e:
            return EvolutionResult.write_failed(version_before, mutation, [str(e)])

        # Stage 5: ONLINE_VERIFY
        ok, errors = online_verifier(mutation, self)
        if not ok:
            self.rollback_mutation(mutation)
            return EvolutionResult.rolled_back(mutation, errors)

        return EvolutionResult.success_result(version_before, self.version, mutation)


def _deep_merge(base: dict, patch: dict) -> None:
    """Merge patch into base in-place (shallow merge for lists)."""
    for key, value in patch.items():
        if key in base and isinstance(base[key], dict) and isinstance(value, dict):
            _deep_merge(base[key], value)
        elif key in base and isinstance(base[key], list) and isinstance(value, list):
            base[key].extend(value)
        else:
            base[key] = value


def _update_manifest_version(manifest_path: Path, new_version: str) -> None:
    """Update package.version and package.updated_at in manifest."""
    import json
    from datetime import datetime, timezone

    manifest = json.loads(manifest_path.read_text())
    manifest["package"]["version"] = new_version
    manifest["package"]["updated_at"] = (
        datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    )
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False))


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
            except (ManifestValidationError, TypeError, ValueError):
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

    def get_layer(self, name: str, layer: str | LayerKind) -> dict | None:
        """Return a structured view of a package layer from its manifest."""
        manifest = self.get_manifest(name)
        if manifest is None:
            return None
        layer_str = layer.value if isinstance(layer, LayerKind) else layer

        if layer_str == "infra":
            return {
                "layer": "infra",
                "runtime": {
                    "kernel_version": manifest.infra.runtime.kernel_version,
                    "min_kernel_version": manifest.infra.runtime.min_kernel_version,
                },
                "plugins": manifest.infra.plugins,
                "packages": manifest.infra.packages,
                "llm": manifest.infra.llm,
            }
        elif layer_str == "capability":
            return {
                "layer": "capability",
                "tools": [
                    {"name": t.name, "version": t.version, "path": t.path,
                     "hash": t.hash, "signature": t.signature}
                    for t in manifest.capability.tools
                ],
                "skills": [
                    {"name": s.name, "maturity": s.maturity, "path": s.path}
                    for s in manifest.capability.skills
                ],
            }
        elif layer_str == "cognitive":
            return {
                "layer": "cognitive",
                "knowledge_graph": manifest.cognitive.knowledge_graph,
                "memory": manifest.cognitive.memory,
                "decisions": manifest.cognitive.decisions,
                "identity": manifest.cognitive.identity,
            }
        elif layer_str == "expression":
            return {
                "layer": "expression",
                "artifacts": [
                    {"type": a.type, "title": a.title, "path": a.path,
                     "format": a.format, "hash": a.hash}
                    for a in manifest.expression.artifacts
                ],
                "goals": manifest.expression.goals,
                "lineage": manifest.expression.lineage,
            }
        return None

    def list_artifacts(self, name: str, type: str = None) -> list[dict]:
        """List artifacts from expression layer, optionally filtered by type."""
        manifest = self.get_manifest(name)
        if manifest is None:
            return []
        arts = manifest.expression.artifacts
        if type:
            arts = [a for a in arts if a.type == type]
        return [
            {"type": a.type, "title": a.title, "path": a.path,
             "format": a.format, "hash": a.hash}
            for a in arts
        ]


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
