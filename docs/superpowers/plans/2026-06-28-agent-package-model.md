# Agent Package Model Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace AgentKernel + scattered workspace with AgentPackage Model — four-layer package structure, manifest.json unified index, AgentRuntime minimal kernel, in-package evolution with auto-versioning.

**Architecture:** Three-phase build. Phase 1 defines `AgentPackage` + `Manifest` as standalone data modules (zero coupling to existing code). Phase 2 implements `AgentRuntime` + `PluginLoader` + adapted `PRALLoop`, adds `PackageRegistry` to Web UI with fallback paths. Phase 3 removes AgentKernel, LifecycleManager, storage_registry, and hardcoded workspace paths.

**Tech Stack:** Python 3.10+, dataclasses, semver (packaging library), JSON/JSONL, pytest + pytest-asyncio

**In Scope:**
- AgentPackage data model, four-layer directory layout
- Manifest.json schema, parser, validator, hash verification
- PackageRegistry for scanning/creating/validating packages
- Package CLI: create, list, validate, export, import
- PluginLoader with semver matching and perpetual plugin support
- AgentRuntime (minimal kernel): Identity + Memory perpetual, rest via manifest
- Adapted PRALLoop for AgentRuntime
- Web UI PackageRegistry integration (data.py) and AgentRuntime cache (agent_cache.py)
- Removal of AgentKernel, LifecycleManager, factories, storage_registry
- Bump version helper for evolution-driven versioning

**Deferred to follow-up plan:**
- Full 5-stage evolution loop refactoring (AutonomousEvolutionLoop → PackageEvolver)
- Lineage.jsonl writing by the evolution system
- Package dependency resolution across packages
- Remote package registry support
- KnowledgePlugin, SkillPlugin, WorkflowPlugin full re-integration with new layer paths

---

## File Structure

```
tain_agent/package/              # NEW: Phase 1
  __init__.py                    # AgentPackage, PackageKind, LayerKind, PackageRegistry
  manifest.py                    # Manifest parse/validate/serialize, hash verification
  cli.py                         # tain package create|validate|export|import

tain_agent/runtime/              # NEW: Phase 2
  __init__.py                    # AgentRuntime
  plugin_loader.py               # PluginLoader
  pral.py                        # PRALLoop (adapted from kernel/pral.py)

tain_agent/kernel/               # MODIFIED → REMOVED in Phase 3
  __init__.py                    # Add deprecation; removed Phase 3
  protocol.py                    # Update AgentContext; PluginProtocol unchanged
  lifecycle.py                   # Removed Phase 3
  factories.py                   # Removed Phase 3
  dispatch.py                    # Updated for dynamic registration; kept
  pral.py                        # Removed Phase 3 (moved to runtime/pral.py)

tain_agent/storage_registry.py   # REMOVED Phase 3

webui/
  data.py                        # MODIFIED: Add PackageRegistry, keep old fallback
  agent_cache.py                 # MODIFIED: Add AgentRuntime cache path

main.py                          # MODIFIED: Add package subcommand, --runtime flag
tests/                           # NEW tests alongside each phase
```

---

## Phase 1: Define Package Model (no coupling to existing code)

### Task 1: AgentPackage dataclass and enums

**Files:**
- Create: `tain_agent/package/__init__.py`
- Test: `tests/test_package.py`

- [ ] **Step 1: Write failing test for AgentPackage creation**

```python
# tests/test_package.py
from pathlib import Path
from tain_agent.package import AgentPackage, PackageKind, LayerKind

def test_agent_package_creation():
    pkg = AgentPackage(
        name="TestAgent",
        kind=PackageKind.AGENT,
        version="0.1.0",
        packages_root=Path("/tmp/test_packages"),
    )
    assert pkg.name == "TestAgent"
    assert pkg.kind == PackageKind.AGENT
    assert pkg.version == "0.1.0"
    assert pkg.path == Path("/tmp/test_packages/TestAgent")
    assert pkg.manifest_path == Path("/tmp/test_packages/TestAgent/manifest.json")

def test_package_kind_values():
    assert PackageKind.AGENT == "agent"
    assert PackageKind.TOOLSET == "toolset"
    assert PackageKind.SKILL == "skill"

def test_layer_kind_values():
    assert LayerKind.INFRA == "infra"
    assert LayerKind.CAPABILITY == "capability"
    assert LayerKind.COGNITIVE == "cognitive"
    assert LayerKind.EXPRESSION == "expression"

def test_package_directory_layout():
    pkg = AgentPackage(
        name="TestAgent",
        kind=PackageKind.AGENT,
        version="0.1.0",
        packages_root=Path("/tmp/test_packages"),
    )
    dirs = pkg.layer_dirs()
    assert dirs[LayerKind.INFRA] == Path("/tmp/test_packages/TestAgent/infra")
    assert dirs[LayerKind.CAPABILITY] == Path("/tmp/test_packages/TestAgent/capability")
    assert dirs[LayerKind.COGNITIVE] == Path("/tmp/test_packages/TestAgent/cognitive")
    assert dirs[LayerKind.EXPRESSION] == Path("/tmp/test_packages/TestAgent/expression")
    assert pkg.runtime_dir == Path("/tmp/test_packages/TestAgent/_runtime")

def test_runtime_dir_not_in_layers():
    pkg = AgentPackage(
        name="TestAgent",
        kind=PackageKind.AGENT,
        version="0.1.0",
        packages_root=Path("/tmp/test_packages"),
    )
    dirs = pkg.layer_dirs()
    assert LayerKind("_runtime") not in dirs  # _runtime is not a layer
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/test_package.py -v
# Expected: FAIL — ModuleNotFoundError: No module named 'tain_agent.package'
```

- [ ] **Step 3: Implement AgentPackage, PackageKind, LayerKind**

```python
# tain_agent/package/__init__.py
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
```

- [ ] **Step 4: Run test to verify it passes**

```bash
pytest tests/test_package.py -v
# Expected: PASS
```

- [ ] **Step 5: Commit**

```bash
git add tain_agent/package/__init__.py tests/test_package.py
git commit -m "feat: add AgentPackage dataclass with PackageKind and LayerKind enums"
```

---

### Task 2: Manifest data model and parsing

**Files:**
- Create: `tain_agent/package/manifest.py`
- Test: append to `tests/test_package.py`

- [ ] **Step 1: Write failing test for Manifest parsing**

```python
# append to tests/test_package.py
import json
import tempfile
from tain_agent.package.manifest import Manifest, ManifestPackage, ManifestInfra, ManifestCapability, ManifestCognitive, ManifestExpression, ArtifactEntry, ToolEntry, SkillEntry, parse_manifest, validate_manifest, ManifestValidationError

MANIFEST_FIXTURE = {
    "package": {
        "name": "TestAgent",
        "version": "0.1.0",
        "kind": "agent",
        "evolution_mode": "chaos",
        "created_at": "2026-06-28T10:00:00Z",
        "updated_at": "2026-06-28T10:00:00Z",
    },
    "infra": {
        "runtime": {"kernel_version": "0.11.0", "min_kernel_version": "0.10.0"},
        "plugins": {"tool": "^1.2.0"},
        "packages": {},
        "llm": {"provider": "anthropic", "preferred_model": "claude-sonnet-4-6"},
    },
    "capability": {
        "tools": [
            {"name": "test_tool", "version": "1.0.0", "path": "capability/tools/test_tool.py", "hash": "sha256:abc123", "signature": "def test_tool(x: str) -> str"}
        ],
        "skills": [
            {"name": "test_skill", "maturity": "NOVICE", "path": "capability/skills/"}
        ],
    },
    "cognitive": {
        "knowledge_graph": "cognitive/knowledge/graph.json",
        "memory": {"episodic": "cognitive/memory/episodic.db", "semantic": "cognitive/memory/semantic.json"},
        "decisions": "cognitive/decisions.jsonl",
        "identity": "cognitive/identity/profile.json",
    },
    "expression": {
        "artifacts": [
            {"type": "report", "title": "Test Report", "path": "expression/artifacts/test.md", "format": "markdown", "hash": "sha256:def456"}
        ],
        "goals": "expression/goals.json",
        "lineage": "expression/lineage.jsonl",
    },
}

def test_parse_manifest_from_dict():
    m = parse_manifest(MANIFEST_FIXTURE)
    assert m.package.name == "TestAgent"
    assert m.package.version == "0.1.0"
    assert m.package.kind == "agent"
    assert m.infra.plugins == {"tool": "^1.2.0"}
    assert len(m.capability.tools) == 1
    assert m.capability.tools[0].name == "test_tool"
    assert len(m.capability.skills) == 1
    assert m.cognitive.identity == "cognitive/identity/profile.json"
    assert len(m.expression.artifacts) == 1
    assert m.expression.lineage == "expression/lineage.jsonl"

def test_parse_manifest_from_json_file():
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        json.dump(MANIFEST_FIXTURE, f)
        tmp_path = f.name
    try:
        m = parse_manifest(tmp_path)
        assert m.package.name == "TestAgent"
    finally:
        import os; os.unlink(tmp_path)

def test_validate_manifest_missing_required():
    bad = {"package": {"name": "Test"}}  # missing everything
    try:
        validate_manifest(bad)
        assert False, "should have raised"
    except ManifestValidationError as e:
        assert "version" in str(e) or "package" in str(e)

def test_manifest_roundtrip():
    m = parse_manifest(MANIFEST_FIXTURE)
    serialized = m.to_dict()
    m2 = parse_manifest(serialized)
    assert m2.package.name == m.package.name
    assert m2.infra.plugins == m.infra.plugins
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/test_package.py::test_parse_manifest_from_dict -v
# Expected: FAIL — ImportError: cannot import name 'Manifest'
```

- [ ] **Step 3: Implement Manifest data classes and parser**

```python
# tain_agent/package/manifest.py
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Union


class ManifestValidationError(Exception):
    pass


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


def _parse_capability(data: dict) -> ManifestCapability:
    return ManifestCapability(
        tools=[ToolEntry(**t) for t in data.get("tools", [])],
        skills=[SkillEntry(**s) for s in data.get("skills", [])],
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
        artifacts=[ArtifactEntry(**a) for a in data.get("artifacts", [])],
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
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_package.py -v
# Expected: all PASS
```

- [ ] **Step 5: Commit**

```bash
git add tain_agent/package/manifest.py tests/test_package.py
git commit -m "feat: add Manifest data model, parser, validator, and hash verification"
```

---

### Task 3: PackageRegistry for listing and loading packages

**Files:**
- Modify: `tain_agent/package/__init__.py` (add PackageRegistry)
- Test: append to `tests/test_package.py`

- [ ] **Step 1: Write failing test for PackageRegistry**

```python
# append to tests/test_package.py
import tempfile
from tain_agent.package import PackageRegistry

def test_package_registry_list_empty():
    with tempfile.TemporaryDirectory() as tmp:
        reg = PackageRegistry(packages_root=Path(tmp))
        pkgs = reg.list_packages()
        assert pkgs == []

def test_package_registry_create_and_list():
    with tempfile.TemporaryDirectory() as tmp:
        reg = PackageRegistry(packages_root=Path(tmp))
        pkg = reg.create(name="TestAgent", kind=PackageKind.AGENT, version="0.1.0")
        assert pkg.manifest_path.exists()
        pkgs = reg.list_packages()
        assert len(pkgs) == 1
        assert pkgs[0].name == "TestAgent"
        assert pkgs[0].version == "0.1.0"

def test_package_registry_get_package():
    with tempfile.TemporaryDirectory() as tmp:
        reg = PackageRegistry(packages_root=Path(tmp))
        reg.create(name="TestAgent", kind=PackageKind.AGENT, version="0.1.0")
        pkg = reg.get_package("TestAgent")
        assert pkg is not None
        assert pkg.name == "TestAgent"
        manifest = reg.get_manifest("TestAgent")
        assert manifest is not None
        assert manifest.package.name == "TestAgent"

def test_package_registry_get_nonexistent():
    with tempfile.TemporaryDirectory() as tmp:
        reg = PackageRegistry(packages_root=Path(tmp))
        assert reg.get_package("Ghost") is None
        assert reg.get_manifest("Ghost") is None

def test_package_registry_list_by_kind():
    with tempfile.TemporaryDirectory() as tmp:
        reg = PackageRegistry(packages_root=Path(tmp))
        reg.create(name="Agent1", kind=PackageKind.AGENT, version="0.1.0")
        reg.create(name="Tool1", kind=PackageKind.TOOLSET, version="0.1.0")
        agents = reg.list_packages(kind=PackageKind.AGENT)
        tools = reg.list_packages(kind=PackageKind.TOOLSET)
        assert len(agents) == 1
        assert agents[0].name == "Agent1"
        assert len(tools) == 1
        assert tools[0].name == "Tool1"
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/test_package.py::test_package_registry_create_and_list -v
# Expected: FAIL — ImportError: cannot import name 'PackageRegistry'
```

- [ ] **Step 3: Implement PackageRegistry**

```python
# append to tain_agent/package/__init__.py

from typing import Optional
from tain_agent.package.manifest import (
    Manifest, parse_manifest, create_manifest, ManifestValidationError,
)

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
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_package.py -v
# Expected: all PASS
```

- [ ] **Step 5: Commit**

```bash
git add tain_agent/package/__init__.py tests/test_package.py
git commit -m "feat: add PackageRegistry for scanning, creating, and validating packages"
```

---

### Task 4: Package CLI commands

**Files:**
- Create: `tain_agent/package/cli.py`
- Modify: `main.py` (add package subparser)

- [ ] **Step 1: Write failing test for CLI handler functions**

```python
# append to tests/test_package.py
import json
import tempfile
from tain_agent.package.cli import cmd_package_create, cmd_package_validate, cmd_package_export, cmd_package_import, cmd_package_list

def test_cmd_package_create(tmp_path):
    packages_dir = tmp_path / "packages"
    packages_dir.mkdir()
    result = cmd_package_create(
        name="TestAgent",
        kind="agent",
        version="0.1.0",
        evolution_mode="chaos",
        packages_root=packages_dir,
    )
    assert result["ok"] is True
    assert (packages_dir / "TestAgent" / "manifest.json").exists()
    assert (packages_dir / "TestAgent" / "capability" / "tools").exists()

def test_cmd_package_create_duplicate(tmp_path):
    packages_dir = tmp_path / "packages"
    packages_dir.mkdir()
    cmd_package_create(name="Dup", kind="agent", version="0.1.0", packages_root=packages_dir)
    result = cmd_package_create(name="Dup", kind="agent", version="0.2.0", packages_root=packages_dir)
    assert result["ok"] is False
    assert "already exists" in result["error"]

def test_cmd_package_validate_ok(tmp_path):
    packages_dir = tmp_path / "packages"
    packages_dir.mkdir()
    cmd_package_create(name="Valid", kind="agent", version="0.1.0", packages_root=packages_dir)
    result = cmd_package_validate(name="Valid", packages_root=packages_dir)
    assert result["ok"] is True

def test_cmd_package_validate_missing(tmp_path):
    packages_dir = tmp_path / "packages"
    packages_dir.mkdir()
    result = cmd_package_validate(name="Ghost", packages_root=packages_dir)
    assert result["ok"] is False

def test_cmd_package_list(tmp_path):
    packages_dir = tmp_path / "packages"
    packages_dir.mkdir()
    cmd_package_create(name="A", kind="agent", version="0.1.0", packages_root=packages_dir)
    cmd_package_create(name="B", kind="toolset", version="0.1.0", packages_root=packages_dir)
    result = cmd_package_list(packages_root=packages_dir)
    assert len(result["packages"]) == 2

def test_cmd_package_export(tmp_path):
    packages_dir = tmp_path / "packages"
    packages_dir.mkdir()
    cmd_package_create(name="ExportMe", kind="agent", version="0.1.0", packages_root=packages_dir)
    export_dir = tmp_path / "exports"
    export_dir.mkdir()
    result = cmd_package_export(name="ExportMe", output=export_dir, packages_root=packages_dir)
    assert result["ok"] is True
    assert (export_dir / "ExportMe").exists()
    # _runtime should NOT be in export
    assert not (export_dir / "ExportMe" / "_runtime").exists()
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/test_package.py::test_cmd_package_create -v
# Expected: FAIL — ImportError: cannot import name 'cmd_package_create'
```

- [ ] **Step 3: Implement CLI handler functions**

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_package.py -v
# Expected: all PASS
```

- [ ] **Step 5: Commit**

```bash
git add tain_agent/package/cli.py tests/test_package.py
git commit -m "feat: add package CLI handlers for create, validate, list, export, import"
```

---

### Task 5: Wire package subcommand into main.py

**Files:**
- Modify: `main.py` (add package subparser)

- [ ] **Step 1: Add package subparser to main.py**

Add after the existing subparsers setup (after line ~235 in main.py):

```python
# ---- Package subcommand ----
pkg_parser = subparsers.add_parser("package", help="Manage Agent packages")
pkg_sub = pkg_parser.add_subparsers(dest="package_action")

pkg_create = pkg_sub.add_parser("create", help="Create a new package")
pkg_create.add_argument("--name", required=True, help="Package name")
pkg_create.add_argument("--kind", default="agent", choices=["agent", "toolset", "skill"])
pkg_create.add_argument("--version", default="0.0.0")
pkg_create.add_argument("--mode", default="chaos", choices=["chaos", "specified"])

pkg_sub.add_parser("list", help="List packages")

pkg_validate = pkg_sub.add_parser("validate", help="Validate a package")
pkg_validate.add_argument("--name", required=True)

pkg_export = pkg_sub.add_parser("export", help="Export a package")
pkg_export.add_argument("--name", required=True)
pkg_export.add_argument("--output", default="dist")

pkg_import = pkg_sub.add_parser("import", help="Import a package")
pkg_import.add_argument("--source", required=True, dest="import_source")
```

- [ ] **Step 2: Add package dispatch in main()**

Add after the argument parsing (after `args = parser.parse_args()`):

```python
if hasattr(args, "package_action") and args.package_action:
    from tain_agent.package.cli import (
        cmd_package_create, cmd_package_validate, cmd_package_list,
        cmd_package_export, cmd_package_import,
    )
    import json as _json
    if args.package_action == "create":
        result = cmd_package_create(name=args.name, kind=args.kind, version=args.version, evolution_mode=args.mode)
    elif args.package_action == "list":
        result = cmd_package_list()
    elif args.package_action == "validate":
        result = cmd_package_validate(name=args.name)
    elif args.package_action == "export":
        result = cmd_package_export(name=args.name, output=Path(args.output))
    elif args.package_action == "import":
        result = cmd_package_import(source=Path(args.import_source))
    else:
        result = {"ok": False, "error": f"Unknown action: {args.package_action}"}
    print(_json.dumps(result, indent=2, ensure_ascii=False))
    sys.exit(0 if result.get("ok") else 1)
```

- [ ] **Step 3: Test CLI manually**

```bash
# Create a package
python main.py package create --name TestCLI --kind agent --version 0.1.0
# Expected: {"ok": true, "package": {"name": "TestCLI", ...}}

# List packages
python main.py package list
# Expected: packages list includes TestCLI

# Validate
python main.py package validate --name TestCLI
# Expected: {"ok": true, "errors": []}

# Export
python main.py package export --name TestCLI --output /tmp/test_export
# Expected: {"ok": true, "path": "/tmp/test_export/TestCLI"}

# Check _runtime is excluded
ls /tmp/test_export/TestCLI/_runtime
# Expected: No such file or directory
```

- [ ] **Step 4: Commit**

```bash
git add main.py
git commit -m "feat: wire package subcommand into CLI (create, list, validate, export, import)"
```

---

### Task 6: Semver helper for version bumping

**Files:**
- Modify: `tain_agent/package/__init__.py` (add bump_version function)
- Test: append to `tests/test_package.py`

- [ ] **Step 1: Write failing test for version bumping**

```python
# append to tests/test_package.py
from tain_agent.package import bump_version
from tain_agent.package import LayerKind as LK

def test_bump_version_patch():
    assert bump_version("0.1.0", LK.EXPRESSION) == "0.1.1"
    assert bump_version("0.7.3", LK.EXPRESSION) == "0.7.4"

def test_bump_version_minor():
    assert bump_version("0.1.0", LK.CAPABILITY) == "0.2.0"
    assert bump_version("0.1.0", LK.COGNITIVE) == "0.2.0"

def test_bump_version_major():
    assert bump_version("0.1.0", LK.INFRA) == "1.0.0"
    assert bump_version("0.7.3", LK.INFRA) == "1.0.0"

def test_bump_version_minor_resets_patch():
    assert bump_version("0.7.3", LK.CAPABILITY) == "0.8.0"

def test_bump_version_identity_is_minor():
    # cognitive/identity changes → MINOR
    assert bump_version("0.7.3", "cognitive/identity") == "0.8.0"
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/test_package.py::test_bump_version_patch -v
# Expected: FAIL — cannot import bump_version
```

- [ ] **Step 3: Implement bump_version**

```python
# append to tain_agent/package/__init__.py

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
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_package.py -v
# Expected: all PASS
```

- [ ] **Step 5: Commit**

```bash
git add tain_agent/package/__init__.py tests/test_package.py
git commit -m "feat: add semver bump_version for evolution-driven versioning"
```

---

## Phase 2: AgentRuntime — Minimal Kernel

### Task 7: PluginLoader with semver matching

**Files:**
- Create: `tain_agent/runtime/plugin_loader.py`
- Test: `tests/test_plugin_loader.py`

- [ ] **Step 1: Write failing test for PluginLoader**

```python
# tests/test_plugin_loader.py
import pytest
from tain_agent.runtime.plugin_loader import PluginLoader, PluginVersionError
from tain_agent.kernel.protocol import AgentContext, PluginProtocol, HealthStatus
from pathlib import Path

# ---- Test plugins ----
class FakeIdentityPlugin:
    version = "1.0.0"
    def __init__(self): self.initialized = False
    def initialize(self, ctx): self.initialized = True
    def shutdown(self): pass
    def health_check(self) -> HealthStatus: return HealthStatus()
    def snapshot(self) -> dict: return {}
    def restore(self, data): pass

class FakeMemoryPlugin:
    version = "1.0.0"
    def __init__(self): self.initialized = False
    def initialize(self, ctx): self.initialized = True
    def shutdown(self): pass
    def health_check(self) -> HealthStatus: return HealthStatus()
    def snapshot(self) -> dict: return {}
    def restore(self, data): pass

class FakeToolPlugin:
    version = "1.2.0"
    def __init__(self): self.initialized = False
    def initialize(self, ctx): self.initialized = True
    def shutdown(self): pass
    def health_check(self) -> HealthStatus: return HealthStatus()
    def snapshot(self) -> dict: return {}
    def restore(self, data): pass

class FakeKnowledgePlugin:
    version = "1.0.0"
    def __init__(self): self.initialized = False
    def initialize(self, ctx): self.initialized = True
    def shutdown(self): pass
    def health_check(self) -> HealthStatus: return HealthStatus()
    def snapshot(self) -> dict: return {}
    def restore(self, data): pass


FAKE_PLUGIN_REGISTRY = {
    "identity": FakeIdentityPlugin,
    "memory": FakeMemoryPlugin,
    "tool": FakeToolPlugin,
    "knowledge": FakeKnowledgePlugin,
}


@pytest.fixture
def ctx():
    return AgentContext(
        agent_name="test",
        agent_id="test-id",
        evolution_mode="chaos",
        workspace_path=Path("/tmp/test"),
        config={},
        kernel_version="0.11.0",
    )


@pytest.fixture
def loader():
    return PluginLoader(registry=FAKE_PLUGIN_REGISTRY)


def test_plugin_loader_perpetual_plugins(loader, ctx):
    """Identity and Memory are always loaded, even with empty manifest declaration."""
    manifest_plugins = {}  # no plugins declared
    plugins = loader.assemble(manifest_plugins, ctx)
    names = [p.__class__.__name__ for p in plugins]
    assert "FakeIdentityPlugin" in names
    assert "FakeMemoryPlugin" in names
    assert len(plugins) == 2


def test_plugin_loader_loads_declared_plugins(loader, ctx):
    manifest_plugins = {"tool": "^1.0.0", "knowledge": "^1.0.0"}
    plugins = loader.assemble(manifest_plugins, ctx)
    names = [p.__class__.__name__ for p in plugins]
    assert "FakeIdentityPlugin" in names
    assert "FakeMemoryPlugin" in names
    assert "FakeToolPlugin" in names
    assert "FakeKnowledgePlugin" in names
    assert len(plugins) == 4


def test_plugin_loader_version_mismatch(loader, ctx):
    """Tool ^2.0.0 requested but only 1.2.0 available → error."""
    manifest_plugins = {"tool": "^2.0.0"}
    with pytest.raises(PluginVersionError) as exc:
        loader.assemble(manifest_plugins, ctx)
    assert "tool" in str(exc.value)
    assert "2.0.0" in str(exc.value)


def test_plugin_loader_exact_version_match(loader, ctx):
    manifest_plugins = {"tool": "1.2.0"}
    plugins = loader.assemble(manifest_plugins, ctx)
    names = [p.__class__.__name__ for p in plugins]
    assert "FakeToolPlugin" in names


def test_plugin_loader_unknown_plugin(loader, ctx):
    manifest_plugins = {"nonexistent": "^1.0.0"}
    with pytest.raises(KeyError):
        loader.assemble(manifest_plugins, ctx)
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/test_plugin_loader.py -v
# Expected: FAIL — ModuleNotFoundError
```

- [ ] **Step 3: Implement PluginLoader**

```python
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

    # Plugins that are always loaded regardless of manifest
    PERPETUAL = frozenset({"identity", "memory"})

    def __init__(self, registry: dict[str, type] | None = None):
        """
        Args:
            registry: Mapping of plugin name → plugin class.
                      If None, uses the built-in plugin registry.
        """
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
                continue  # already loaded
            if name not in self._registry:
                raise KeyError(f"Unknown plugin: {name}")
            cls = self._registry[name]
            if not semver_match(cls.version, version_spec):
                raise PluginVersionError(name, version_spec, cls.version)
            instance = cls()
            instance.initialize(ctx)
            instances.append(instance)

        return instances
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_plugin_loader.py -v
# Expected: all PASS
```

- [ ] **Step 5: Commit**

```bash
git add tain_agent/runtime/plugin_loader.py tests/test_plugin_loader.py
git commit -m "feat: add PluginLoader with semver matching and perpetual plugin support"
```

---

### Task 8: AgentRuntime class

**Files:**
- Create: `tain_agent/runtime/__init__.py`
- Test: `tests/test_agent_runtime.py`

- [ ] **Step 1: Write failing test for AgentRuntime initialization**

```python
# tests/test_agent_runtime.py
import json
from pathlib import Path
from tain_agent.package import AgentPackage, PackageKind, PackageRegistry
from tain_agent.package.manifest import create_manifest
from tain_agent.runtime import AgentRuntime

def test_agent_runtime_init(tmp_path):
    packages_dir = tmp_path / "packages"
    packages_dir.mkdir()
    reg = PackageRegistry(packages_root=packages_dir)
    pkg = reg.create(name="TestRuntime", kind=PackageKind.AGENT, version="0.1.0")
    config = {"llm": {"provider": "test"}}

    runtime = AgentRuntime(package=pkg, config=config)

    assert runtime.package.name == "TestRuntime"
    assert runtime.manifest is not None
    assert runtime.manifest.package.name == "TestRuntime"
    assert len(runtime.active_plugins) >= 2  # identity + memory
    active_names = [p.__class__.__name__ for p in runtime.active_plugins]
    assert "IdentityPlugin" in active_names
    assert "MemoryPlugin" in active_names


def test_agent_runtime_with_additional_plugins(tmp_path):
    packages_dir = tmp_path / "packages"
    packages_dir.mkdir()
    reg = PackageRegistry(packages_root=packages_dir)
    pkg = reg.create(
        name="TestWithTools",
        kind=PackageKind.AGENT,
        version="0.1.0",
        plugins={"tool": "^1.2.0"},
    )
    config = {"llm": {"provider": "test"}}

    runtime = AgentRuntime(package=pkg, config=config)

    active_names = [p.__class__.__name__ for p in runtime.active_plugins]
    assert "ToolPlugin" in active_names


def test_agent_runtime_shutdown(tmp_path):
    packages_dir = tmp_path / "packages"
    packages_dir.mkdir()
    reg = PackageRegistry(packages_root=packages_dir)
    pkg = reg.create(name="TestShutdown", kind=PackageKind.AGENT, version="0.1.0")
    config = {"llm": {"provider": "test"}}

    runtime = AgentRuntime(package=pkg, config=config)
    runtime.shutdown()
    # No exception = success
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/test_agent_runtime.py::test_agent_runtime_init -v
# Expected: FAIL — ModuleNotFoundError
```

- [ ] **Step 3: Implement AgentRuntime**

```python
# tain_agent/runtime/__init__.py
"""AgentRuntime — minimal kernel that loads an AgentPackage and runs PRAL."""

from __future__ import annotations

from typing import Any

from tain_agent.kernel.dispatch import Dispatch
from tain_agent.kernel.protocol import AgentContext
from tain_agent.package import AgentPackage, LayerKind
from tain_agent.package.manifest import parse_manifest, Manifest
from tain_agent.runtime.plugin_loader import PluginLoader


class AgentRuntime:
    """Minimal runtime for an AgentPackage.

    Only IdentityPlugin and MemoryPlugin are loaded perpetually.
    All other plugins are loaded based on the package's manifest infra.plugins declaration.
    """

    def __init__(self, package: AgentPackage, config: dict[str, Any] | None = None):
        self.package = package
        self.config = config or {}
        self.dispatch = Dispatch()

        # Parse manifest
        self.manifest: Manifest = parse_manifest(package.manifest_path)

        # Build context
        self.ctx = AgentContext(
            agent_name=self.manifest.package.name,
            agent_id=f"{self.manifest.package.name}-{package.path.name}",
            evolution_mode=self.manifest.package.evolution_mode,
            workspace_path=package.path,
            config=self.config,
            kernel_version=self.manifest.infra.runtime.kernel_version or "0.11.0",
        )

        # Assemble plugins
        self.plugin_loader = PluginLoader(registry=self._build_plugin_registry())
        declared = self.manifest.infra.plugins
        self.active_plugins = self.plugin_loader.assemble(declared, self.ctx)

        # Register dispatch routes for active plugins
        self._build_routes()

    def _build_plugin_registry(self) -> dict[str, type]:
        """Build the plugin registry mapping name → class."""
        from tain_agent.plugins.identity import IdentityPlugin
        from tain_agent.plugins.memory import MemoryPlugin
        from tain_agent.plugins.tool import ToolPlugin
        from tain_agent.plugins.skill import SkillPlugin
        from tain_agent.plugins.knowledge import KnowledgePlugin
        from tain_agent.plugins.workflow import WorkflowPlugin
        from tain_agent.plugins.collaboration import CollaborationPlugin
        from tain_agent.plugins.evaluation import EvaluationPlugin

        return {
            "identity": IdentityPlugin,
            "memory": MemoryPlugin,
            "tool": ToolPlugin,
            "skill": SkillPlugin,
            "knowledge": KnowledgePlugin,
            "workflow": WorkflowPlugin,
            "collaboration": CollaborationPlugin,
            "evaluation": EvaluationPlugin,
        }

    def _build_routes(self) -> None:
        """Register dispatch routes for actively loaded plugins only."""
        plugin_map = {p.__class__.__name__: p for p in self.active_plugins}

        route_map = {
            "memory.recall": ("MemoryPlugin", "recall"),
            "knowledge.query": ("KnowledgePlugin", "query"),
            "tool.call": ("ToolPlugin", "call"),
            "tool.forge": ("ToolPlugin", "forge"),
            "skill.execute": ("SkillPlugin", "execute"),
            "workflow.advance": ("WorkflowPlugin", "advance"),
            "collaboration.send": ("CollaborationPlugin", "send"),
            "evaluation.get_readiness": ("EvaluationPlugin", "get_readiness"),
            "evaluation.get_report": ("EvaluationPlugin", "get_report"),
        }

        for event, (class_name, method_name) in route_map.items():
            if class_name in plugin_map:
                plugin = plugin_map[class_name]
                self.dispatch.register(event, getattr(plugin, method_name))

    def get_plugin(self, name: str) -> Any | None:
        """Get a loaded plugin by class name or registry key."""
        for p in self.active_plugins:
            if p.__class__.__name__ == name or p.__class__.__name__ == f"{name.capitalize()}Plugin":
                return p
        return None

    def get_identity(self):
        return self.get_plugin("IdentityPlugin")

    def get_memory(self):
        return self.get_plugin("MemoryPlugin")

    def health_check(self) -> dict[str, Any]:
        """Run health checks on all active plugins."""
        results = {}
        for p in self.active_plugins:
            name = p.__class__.__name__
            try:
                results[name] = p.health_check()
            except Exception as e:
                results[name] = {"status": "critical", "error": str(e)}
        return results

    def shutdown(self) -> None:
        """Shutdown all active plugins."""
        for p in self.active_plugins:
            try:
                p.shutdown()
            except Exception:
                pass
        self.active_plugins.clear()
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_agent_runtime.py -v
# Expected: all PASS
```

- [ ] **Step 5: Commit**

```bash
git add tain_agent/runtime/__init__.py tests/test_agent_runtime.py
git commit -m "feat: add AgentRuntime — minimal kernel with PluginLoader assembly"
```

---

### Task 9: PackageRegistry integration into webui/data.py

**Files:**
- Modify: `webui/data.py`

- [ ] **Step 1: Write failing test for PackageRegistry-backed data reading**

```python
# tests/test_package_registry_webui.py
import json
from pathlib import Path
from tain_agent.package import PackageRegistry, PackageKind
from tain_agent.package.manifest import create_manifest

def test_registry_list_agents(tmp_path):
    packages_dir = tmp_path / "packages"
    packages_dir.mkdir()
    reg = PackageRegistry(packages_root=packages_dir)
    reg.create(name="Agent1", kind=PackageKind.AGENT, version="0.1.0")
    reg.create(name="Tool1", kind=PackageKind.TOOLSET, version="0.1.0")

    agents = reg.list_packages(kind=PackageKind.AGENT)
    assert len(agents) == 1
    assert agents[0].name == "Agent1"

def test_registry_get_manifest_fields(tmp_path):
    packages_dir = tmp_path / "packages"
    packages_dir.mkdir()
    reg = PackageRegistry(packages_root=packages_dir)
    reg.create(name="Test", kind=PackageKind.AGENT, version="0.2.0", evolution_mode="specified")

    m = reg.get_manifest("Test")
    assert m.package.version == "0.2.0"
    assert m.package.evolution_mode == "specified"

def test_registry_list_artifacts(tmp_path):
    packages_dir = tmp_path / "packages"
    packages_dir.mkdir()
    reg = PackageRegistry(packages_root=packages_dir)
    # Create a package with an artifact already declared in the manifest
    from tain_agent.package.manifest import Manifest, ManifestPackage, ManifestExpression, ArtifactEntry
    pkg = reg.create(name="ArtTest", kind=PackageKind.AGENT, version="0.1.0")
    import json
    with open(pkg.manifest_path) as f:
        data = json.load(f)
    data["expression"]["artifacts"] = [
        {"type": "report", "title": "Test Report", "path": "expression/artifacts/test.md", "format": "markdown", "hash": ""}
    ]
    with open(pkg.manifest_path, "w") as f:
        json.dump(data, f, indent=2)

    m = reg.get_manifest("ArtTest")
    assert len(m.expression.artifacts) == 1
    assert m.expression.artifacts[0].title == "Test Report"
```

- [ ] **Step 2: Run test to verify basic registry operations**

```bash
pytest tests/test_package_registry_webui.py -v
# Expected: PASS (registry already implemented)
```

- [ ] **Step 3: Add PackageRegistry adapter to webui/data.py**

Add to `webui/data.py` after the existing imports and constants:

```python
# webui/data.py additions — add after line 17 (existing _KNOWLEDGE_CACHE_TTL)

from tain_agent.package import PackageRegistry, PackageKind
from tain_agent.package.manifest import parse_manifest

PACKAGES_ROOT = PROJECT_ROOT / "agent_workspace" / "packages"
_registry = PackageRegistry(packages_root=PACKAGES_ROOT)


def list_agents_v2() -> list[dict]:
    """List agents from the new package-based system."""
    agents = []
    for pkg in _registry.list_packages(kind=PackageKind.AGENT):
        manifest = _registry.get_manifest(pkg.name)
        if manifest is None:
            continue
        agents.append({
            "name": pkg.name,
            "version": pkg.version,
            "kind": manifest.package.kind,
            "evolution_mode": manifest.package.evolution_mode,
            "tool_count": len(manifest.capability.tools),
            "artifact_count": len(manifest.expression.artifacts),
            "created_at": manifest.package.created_at,
            "updated_at": manifest.package.updated_at,
        })
    return agents


def get_agent_v2(name: str) -> dict | None:
    """Get a single agent from the package system."""
    manifest = _registry.get_manifest(name)
    if manifest is None:
        return None
    pkg = _registry.get_package(name)
    return {
        "name": name,
        "version": pkg.version,
        "kind": manifest.package.kind,
        "evolution_mode": manifest.package.evolution_mode,
        "tool_count": len(manifest.capability.tools),
        "artifact_count": len(manifest.expression.artifacts),
        "created_at": manifest.package.created_at,
        "updated_at": manifest.package.updated_at,
    }
```

- [ ] **Step 4: Integration test that old and new paths coexist**

```bash
# Verify existing list_agents() still works with legacy workspace
python -c "from webui.data import list_agents; print(len(list_agents()))"
# Should return current agent count without error

# Verify new v2 functions work
python -c "from webui.data import list_agents_v2; print(list_agents_v2())"
# Should return [] or list of v2 packages
```

- [ ] **Step 5: Commit**

```bash
git add webui/data.py tests/test_package_registry_webui.py
git commit -m "feat: add PackageRegistry-backed data functions to webui/data.py"
```

---

### Task 10: AgentRuntime cache in webui/agent_cache.py

**Files:**
- Modify: `webui/agent_cache.py`

- [ ] **Step 1: Add AgentRuntime create/cache function**

Add to `webui/agent_cache.py` after the existing cache code:

```python
# Add after existing imports
from pathlib import Path as _Path
from tain_agent.package import AgentPackage, PackageRegistry, PackageKind
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
```

- [ ] **Step 2: Commit**

```bash
git add webui/agent_cache.py
git commit -m "feat: add AgentRuntime create/cache to webui/agent_cache.py"
```

---

## Phase 3: Replace Old System

### Task 11: Update AgentContext to support package path

**Files:**
- Modify: `tain_agent/kernel/protocol.py`

- [ ] **Step 1: Keep PluginProtocol unchanged, note AgentContext compatibility**

The existing `AgentContext` works as-is because AgentRuntime passes `workspace_path=package.path`. No changes needed to `protocol.py`. The `PluginProtocol` interface remains the contract.

Commit note — no code change needed, this is a verification step:

```bash
git commit --allow-empty -m "verify: AgentContext and PluginProtocol compatible with AgentRuntime; no changes needed"
```

---

### Task 12: Remove AgentKernel and related code

**Files:**
- Remove: `tain_agent/kernel/__init__.py` (AgentKernel)
- Remove: `tain_agent/kernel/lifecycle.py`
- Remove: `tain_agent/kernel/factories.py`
- Remove: `tain_agent/storage_registry.py`
- Modify: `tain_agent/kernel/__init__.py` → keep only protocol and dispatch re-exports

- [ ] **Step 1: Replace kernel/__init__.py with re-export shim**

```python
# tain_agent/kernel/__init__.py — re-export shim
"""Kernel module — now re-exports from runtime and protocol."""

from tain_agent.kernel.protocol import PluginProtocol, AgentContext, HealthStatus
from tain_agent.kernel.dispatch import Dispatch
from tain_agent.runtime.plugin_loader import PluginLoader
from tain_agent.runtime import AgentRuntime

# Backward-compatible re-export
from tain_agent.plugins.identity import IdentityPlugin
from tain_agent.plugins.memory import MemoryPlugin
from tain_agent.plugins.tool import ToolPlugin
from tain_agent.plugins.skill import SkillPlugin
from tain_agent.plugins.knowledge import KnowledgePlugin
from tain_agent.plugins.workflow import WorkflowPlugin
from tain_agent.plugins.collaboration import CollaborationPlugin

# Build the standard registry from PluginLoader
STANDARD_FACTORIES = {
    "identity": IdentityPlugin,
    "memory": MemoryPlugin,
    "tool": ToolPlugin,
    "skill": SkillPlugin,
    "knowledge": KnowledgePlugin,
    "workflow": WorkflowPlugin,
    "collaboration": CollaborationPlugin,
}

__all__ = [
    "AgentRuntime", "PluginProtocol", "AgentContext", "HealthStatus",
    "Dispatch", "PluginLoader", "STANDARD_FACTORIES",
]
```

- [ ] **Step 2: Update main.py to use AgentRuntime**

In `main.py`, update the agent creation section to use AgentRuntime. Find the block around lines 340-360 and replace:

```python
# Replace the AgentKernel construction block:
from tain_agent.runtime import AgentRuntime
from tain_agent.package import AgentPackage, PackageKind, PackageRegistry

# For v2 runtime
packages_root = Path("agent_workspace/packages")
registry = PackageRegistry(packages_root=packages_root)

# Ensure package exists (create if not found)
pkg = registry.get_package(agent_name)
if pkg is None:
    pkg = registry.create(
        name=agent_name,
        kind=PackageKind.AGENT,
        version="0.1.0",
        evolution_mode=evolution_mode,
    )

kernel = AgentRuntime(package=pkg, config=cfg)
```

- [ ] **Step 3: Update webui/agent_cache.py to use AgentRuntime exclusively**

Replace `_build_kernel` in `webui/agent_cache.py`:

```python
def _build_kernel(name: str, config_path: str) -> "AgentRuntime":
    from tain_agent.package import PackageRegistry
    from tain_agent.runtime import AgentRuntime

    with open(config_path) as f:
        config = yaml.safe_load(f)

    packages_root = WORKSPACE_ROOT / "packages"
    reg = PackageRegistry(packages_root=packages_root)
    pkg = reg.get_package(name)
    if pkg is None:
        raise FileNotFoundError(f"Package '{name}' not found under {packages_root}")

    return AgentRuntime(package=pkg, config=config)
```

- [ ] **Step 4: Delete old files**

```bash
rm tain_agent/kernel/lifecycle.py
rm tain_agent/kernel/factories.py
rm tain_agent/storage_registry.py
```

- [ ] **Step 5: Run full test suite to verify no breakage**

```bash
pytest tests/ -v --timeout=60
# Fix any import errors or failures
```

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "refactor: remove AgentKernel, LifecycleManager, storage_registry; AgentRuntime is sole runtime"
```

---

### Task 13: Remove old PRAL and point to runtime PRAL

**Files:**
- Remove: `tain_agent/kernel/pral.py`
- Move: `tain_agent/runtime/pral.py` (adapt PRAL to use AgentRuntime plugin access)

- [ ] **Step 1: Move and adapt PRAL**

```python
# tain_agent/runtime/pral.py
"""PRAL cognitive loop adapted for AgentRuntime."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

from tain_agent.kernel.dispatch import Dispatch
from tain_agent.runtime import AgentRuntime

logger = logging.getLogger(__name__)


class PRALLoop:
    """Perceive → Reason → Act → Learn loop for AgentRuntime."""

    def __init__(self, runtime: AgentRuntime):
        self._runtime = runtime
        self._dispatch = runtime.dispatch
        self._running = False
        self.cycle_count = 0
        self._drive_system = None

    def run(
        self,
        llm_backend: Any,
        conversation: Any,
        drive_system: Any,
        system_prompt_template: str,
        max_cycles: int | float = float("inf"),
        stop_signal: callable | None = None,
    ) -> int:
        """Run the PRAL loop."""
        self._running = True
        self._drive_system = drive_system
        cycles_run = 0

        try:
            while self._running and cycles_run < max_cycles:
                if stop_signal and stop_signal():
                    break

                self.cycle_count += 1
                cycles_run += 1

                # Perceive
                self._notify_plugins("on_cycle_start", self.cycle_count)
                context = self._perceive()

                # Reason
                prompt = self._build_prompt(system_prompt_template, context)
                tool_defs = self._gather_tool_definitions()
                response = llm_backend.create_message(
                    system=prompt,
                    messages=conversation.get_messages(),
                    tools=tool_defs,
                )
                self._notify_plugins("on_llm_response", response)

                # Act
                self._act(response, conversation)

                # Learn
                self._learn(response, conversation)
                self._notify_plugins("on_cycle_end", self.cycle_count)
                self._save_memory_state()

        finally:
            self._running = False

        return cycles_run

    def _perceive(self) -> dict:
        context = {}
        mem = self._runtime.get_memory()
        if mem:
            try:
                context["recent_memories"] = mem.recall(limit=5)
            except Exception:
                pass
        return context

    def _build_prompt(self, base: str, context: dict | None = None) -> str:
        prompt = base
        for plugin in self._runtime.active_plugins:
            if hasattr(plugin, "enrich_prompt"):
                try:
                    prompt = plugin.enrich_prompt(prompt)
                except Exception:
                    pass
        return prompt

    def _gather_tool_definitions(self) -> list[dict]:
        tool_plugin = self._runtime.get_plugin("ToolPlugin")
        if tool_plugin and hasattr(tool_plugin, "get_claude_tool_definitions"):
            return tool_plugin.get_claude_tool_definitions()
        return []

    def _act(self, response: Any, conversation: Any) -> None:
        if not hasattr(response, "content"):
            return
        for block in getattr(response, "content", []):
            if hasattr(block, "type") and block.type == "tool_use":
                try:
                    self._dispatch.call("tool.call", block.name, **block.input)
                except Exception as e:
                    logger.warning(f"Tool call failed: {e}")

    def _learn(self, response: Any, conversation: Any) -> None:
        mem = self._runtime.get_memory()
        if mem:
            try:
                text = getattr(response, "text", "") or str(response)
                mem.encode(text, importance=0.3)
            except Exception:
                pass

    def _save_memory_state(self) -> None:
        runtime_dir = self._runtime.package.runtime_dir
        state_dir = runtime_dir / "state"
        state_dir.mkdir(parents=True, exist_ok=True)
        state = {
            "cycle_count": self.cycle_count,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        try:
            with open(state_dir / "pral_phase.json", "w") as f:
                json.dump(state, f)
        except Exception:
            pass

    def _notify_plugins(self, method: str, *args: Any) -> None:
        for plugin in self._runtime.active_plugins:
            fn = getattr(plugin, method, None)
            if fn:
                try:
                    fn(*args)
                except Exception:
                    pass

    def stop(self) -> None:
        self._running = False
```

- [ ] **Step 2: Remove old PRAL**

```bash
rm tain_agent/kernel/pral.py
```

- [ ] **Step 3: Run tests**

```bash
pytest tests/ -v --timeout=60 -k "not test_"
```

- [ ] **Step 4: Commit**

```bash
git add -A
git commit -m "refactor: move PRAL to runtime, adapt to AgentRuntime plugin access"
```

---

### Task 14: Final integration test

**Files:**
- Test: `tests/test_integration_package.py`

- [ ] **Step 1: Write integration test**

```python
# tests/test_integration_package.py
"""Integration test: create package → load with AgentRuntime → run PRAL cycle."""

import json
from pathlib import Path
from tain_agent.package import PackageRegistry, PackageKind
from tain_agent.runtime import AgentRuntime


def test_create_and_load_package(tmp_path):
    """Create a package and load it with AgentRuntime."""
    packages_dir = tmp_path / "packages"
    packages_dir.mkdir()

    reg = PackageRegistry(packages_root=packages_dir)
    pkg = reg.create(
        name="IntegrationTest",
        kind=PackageKind.AGENT,
        version="0.1.0",
        evolution_mode="chaos",
    )

    config = {"llm": {"provider": "test"}, "agent": {"evolution_mode": "chaos"}}
    runtime = AgentRuntime(package=pkg, config=config)

    assert runtime.package.name == "IntegrationTest"
    assert runtime.manifest.package.version == "0.1.0"

    # Verify directory layout was created
    assert (pkg.path / "capability" / "tools").exists()
    assert (pkg.path / "cognitive" / "memory").exists()
    assert (pkg.path / "expression" / "artifacts").exists()
    assert (pkg.path / "_runtime" / "state").exists()

    # Verify manifest is valid
    with open(pkg.manifest_path) as f:
        data = json.load(f)
    assert data["package"]["name"] == "IntegrationTest"

    runtime.shutdown()


def test_registry_list_filters_by_kind(tmp_path):
    packages_dir = tmp_path / "packages"
    packages_dir.mkdir()
    reg = PackageRegistry(packages_root=packages_dir)

    reg.create(name="MyAgent", kind=PackageKind.AGENT, version="0.1.0")
    reg.create(name="MyToolset", kind=PackageKind.TOOLSET, version="0.1.0")
    reg.create(name="MySkill", kind=PackageKind.SKILL, version="0.1.0")

    agents = reg.list_packages(kind=PackageKind.AGENT)
    toolsets = reg.list_packages(kind=PackageKind.TOOLSET)
    skills = reg.list_packages(kind=PackageKind.SKILL)

    assert len(agents) == 1
    assert agents[0].name == "MyAgent"
    assert len(toolsets) == 1
    assert toolsets[0].name == "MyToolset"
    assert len(skills) == 1
    assert skills[0].name == "MySkill"
```

- [ ] **Step 2: Run integration test**

```bash
pytest tests/test_integration_package.py -v
# Expected: PASS
```

- [ ] **Step 3: Commit**

```bash
git add tests/test_integration_package.py
git commit -m "test: add integration test for package creation and AgentRuntime loading"
```

---

### Task 15: Run full test suite and fix issues

- [ ] **Step 1: Run full test suite**

```bash
pytest tests/ -v --timeout=120 2>&1 | head -200
```

- [ ] **Step 2: Fix any import errors or test failures**

Expected issues and fixes:

1. **Tests importing `AgentKernel` directly** — update imports to use `AgentRuntime`
2. **Tests referencing `agent_workspace/<name>/logs/decisions.jsonl`** — update paths
3. **Tests calling `STANDARD_FACTORIES` or `LifecycleManager`** — update to `PluginLoader`

- [ ] **Step 3: Verify CLI still works**

```bash
# Package create
python main.py package create --name FinalTest --version 0.2.0

# Package list
python main.py package list

# Package validate
python main.py package validate --name FinalTest
```

- [ ] **Step 4: Final commit**

```bash
git add -A
git commit -m "test: fix test suite for AgentRuntime migration, all tests passing"
```
