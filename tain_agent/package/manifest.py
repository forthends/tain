# tain_agent/package/manifest.py
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Union


class ManifestValidationError(Exception):
    pass


class PackageIntegrityError(Exception):
    """Raised when a package's declared file hashes don't match actual files."""


# ---- Sub-models ----

@dataclass
class ManifestPackage:
    name: str
    version: str
    kind: str  # "agent" | "toolset" | "skill"
    evolution_mode: str = "chaos"
    created_at: str = ""
    updated_at: str = ""


@dataclass
class ManifestRuntime:
    kernel_version: str = ""
    min_kernel_version: str = ""


@dataclass
class ManifestInfra:
    runtime: ManifestRuntime = field(default_factory=ManifestRuntime)
    plugins: dict[str, str] = field(default_factory=dict)
    packages: dict[str, str] = field(default_factory=dict)
    llm: dict[str, str] = field(default_factory=dict)


@dataclass
class ToolEntry:
    name: str
    version: str
    path: str
    hash: str = ""
    signature: str = ""


@dataclass
class SkillEntry:
    name: str
    maturity: str = "NOVICE"
    path: str = ""


@dataclass
class ManifestCapability:
    tools: list[ToolEntry] = field(default_factory=list)
    skills: list[SkillEntry] = field(default_factory=list)


@dataclass
class ManifestCognitive:
    knowledge_graph: str = ""
    memory: dict[str, str] = field(default_factory=lambda: {"episodic": "", "semantic": ""})
    decisions: str = ""
    identity: str = ""


@dataclass
class ArtifactEntry:
    type: str
    title: str
    path: str
    format: str = "markdown"
    hash: str = ""


@dataclass
class ManifestExpression:
    artifacts: list[ArtifactEntry] = field(default_factory=list)
    goals: str = ""
    lineage: str = ""


@dataclass
class Manifest:
    package: ManifestPackage
    infra: ManifestInfra = field(default_factory=ManifestInfra)
    capability: ManifestCapability = field(default_factory=ManifestCapability)
    cognitive: ManifestCognitive = field(default_factory=ManifestCognitive)
    expression: ManifestExpression = field(default_factory=ManifestExpression)

    def to_dict(self) -> dict:
        return _serialize_manifest(self)

    def to_json(self, path: Path) -> None:
        with open(path, "w") as f:
            json.dump(self.to_dict(), f, indent=2, ensure_ascii=False)

    def verify_hashes(self, package_root: Path) -> list[str]:
        """Verify all declared file hashes. Returns list of errors (empty = ok)."""
        errors = []
        for tool in self.capability.tools:
            if tool.hash:
                file_path = package_root / tool.path
                if not file_path.exists():
                    errors.append(f"Tool file missing: {tool.path}")
                else:
                    actual = _sha256(file_path)
                    if actual != tool.hash:
                        errors.append(f"Hash mismatch for {tool.path}: expected {tool.hash}, got {actual}")
        for art in self.expression.artifacts:
            if art.hash:
                file_path = package_root / art.path
                if not file_path.exists():
                    errors.append(f"Artifact file missing: {art.path}")
                else:
                    actual = _sha256(file_path)
                    if actual != art.hash:
                        errors.append(f"Hash mismatch for {art.path}: expected {art.hash}, got {actual}")
        return errors


# ---- Parse functions ----

def _parse_package(data: dict) -> ManifestPackage:
    return ManifestPackage(
        name=data.get("name", ""),
        version=data.get("version", "0.0.0"),
        kind=data.get("kind", "agent"),
        evolution_mode=data.get("evolution_mode", "chaos"),
        created_at=data.get("created_at", ""),
        updated_at=data.get("updated_at", ""),
    )


def _parse_infra(data: dict) -> ManifestInfra:
    runtime_data = data.get("runtime", {})
    return ManifestInfra(
        runtime=ManifestRuntime(
            kernel_version=runtime_data.get("kernel_version", ""),
            min_kernel_version=runtime_data.get("min_kernel_version", ""),
        ),
        plugins=data.get("plugins", {}),
        packages=data.get("packages", {}),
        llm=data.get("llm", {}),
    )


def _coerce_tool_entry(t) -> ToolEntry:
    """Convert a string path or dict into a ToolEntry.

    Legacy manifests stored tools as plain file-path strings.
    Normalise those to ToolEntry with path extracted from the string.
    """
    if isinstance(t, str):
        stem = Path(t).stem
        return ToolEntry(name=stem, version="0.0.0", path=t)
    return ToolEntry(**t)


def _coerce_skill_entry(s) -> SkillEntry:
    """Convert a string path or dict into a SkillEntry."""
    if isinstance(s, str):
        stem = Path(s).stem
        return SkillEntry(name=stem, maturity="NOVICE", path=s)
    return SkillEntry(**s)


def _coerce_artifact_entry(a) -> ArtifactEntry:
    """Convert a string path or dict into an ArtifactEntry.

    Legacy manifests stored artifacts as plain file-path strings.
    Normalise those to ArtifactEntry with type inferred from the path.
    """
    if isinstance(a, str):
        p = Path(a)
        stem = p.stem
        # Infer type from the parent directory name
        parent = p.parent.name
        return ArtifactEntry(type=parent, title=stem, path=a)
    return ArtifactEntry(**a)


def _parse_capability(data: dict) -> ManifestCapability:
    return ManifestCapability(
        tools=[_coerce_tool_entry(t) for t in data.get("tools", [])],
        skills=[_coerce_skill_entry(s) for s in data.get("skills", [])],
    )


def _parse_cognitive(data: dict) -> ManifestCognitive:
    return ManifestCognitive(
        knowledge_graph=data.get("knowledge_graph", ""),
        memory=data.get("memory", {"episodic": "", "semantic": ""}),
        decisions=data.get("decisions", ""),
        identity=data.get("identity", ""),
    )


def _parse_expression(data: dict) -> ManifestExpression:
    return ManifestExpression(
        artifacts=[_coerce_artifact_entry(a) for a in data.get("artifacts", [])],
        goals=data.get("goals", ""),
        lineage=data.get("lineage", ""),
    )


def parse_manifest(source: Union[dict, str, Path]) -> Manifest:
    """Parse manifest from dict, JSON file path, or JSON string."""
    if isinstance(source, dict):
        data = source
    elif isinstance(source, (str, Path)):
        path = Path(source)
        if path.suffix == ".json" and path.exists():
            with open(path) as f:
                data = json.load(f)
        else:
            data = json.loads(str(source))
    else:
        raise ManifestValidationError(f"Unsupported manifest source type: {type(source)}")
    return Manifest(
        package=_parse_package(data.get("package", {})),
        infra=_parse_infra(data.get("infra", {})),
        capability=_parse_capability(data.get("capability", {})),
        cognitive=_parse_cognitive(data.get("cognitive", {})),
        expression=_parse_expression(data.get("expression", {})),
    )


def validate_manifest(data: dict) -> None:
    """Validate raw manifest dict. Raises ManifestValidationError on failure."""
    if "package" not in data:
        raise ManifestValidationError("Missing required key: 'package'")
    pkg = data["package"]
    if "name" not in pkg or not pkg["name"]:
        raise ManifestValidationError("package.name is required")
    if "version" not in pkg or not pkg["version"]:
        raise ManifestValidationError("package.version is required")


def create_manifest(
    name: str,
    kind: str = "agent",
    version: str = "0.0.0",
    evolution_mode: str = "chaos",
    plugins: dict[str, str] | None = None,
) -> Manifest:
    """Factory for creating a minimal valid manifest."""
    from datetime import datetime, timezone
    now_ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return Manifest(
        package=ManifestPackage(
            name=name, version=version, kind=kind, evolution_mode=evolution_mode,
            created_at=now_ts, updated_at=now_ts,
        ),
        infra=ManifestInfra(plugins=plugins or {}),
    )


# ---- Internal helpers ----

def _sha256(path: Path) -> str:
    """Compute SHA-256 hash of a file, returned as 'sha256:<hex>'."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return f"sha256:{h.hexdigest()}"


def _serialize_manifest(m: Manifest) -> dict:
    """Serialize Manifest to a plain dict for JSON output."""
    return {
        "package": {
            "name": m.package.name,
            "version": m.package.version,
            "kind": m.package.kind,
            "evolution_mode": m.package.evolution_mode,
            "created_at": m.package.created_at,
            "updated_at": m.package.updated_at,
        },
        "infra": {
            "runtime": {
                "kernel_version": m.infra.runtime.kernel_version,
                "min_kernel_version": m.infra.runtime.min_kernel_version,
            },
            "plugins": m.infra.plugins,
            "packages": m.infra.packages,
            "llm": m.infra.llm,
        },
        "capability": {
            "tools": [{"name": t.name, "version": t.version, "path": t.path, "hash": t.hash, "signature": t.signature} for t in m.capability.tools],
            "skills": [{"name": s.name, "maturity": s.maturity, "path": s.path} for s in m.capability.skills],
        },
        "cognitive": {
            "knowledge_graph": m.cognitive.knowledge_graph,
            "memory": m.cognitive.memory,
            "decisions": m.cognitive.decisions,
            "identity": m.cognitive.identity,
        },
        "expression": {
            "artifacts": [{"type": a.type, "title": a.title, "path": a.path, "format": a.format, "hash": a.hash} for a in m.expression.artifacts],
            "goals": m.expression.goals,
            "lineage": m.expression.lineage,
        },
    }
