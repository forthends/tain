import json
import os
import tempfile

import pytest
from pathlib import Path
from tain_agent.package import AgentPackage, PackageKind, LayerKind, PackageRegistry


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
    # _runtime is not a valid LayerKind
    with pytest.raises(ValueError):
        LayerKind("_runtime")
    # _runtime value is not among layer values
    assert "_runtime" not in [layer.value for layer in LayerKind]


# ---- AgentContext package/manifest/active_plugins tests (Task 2) ----

from tain_agent.kernel.protocol import AgentContext


def test_agent_context_has_package_fields():
    ctx = AgentContext(
        agent_name="test",
        agent_id="test-id",
        evolution_mode="chaos",
        workspace_path=Path("/tmp/test"),
        config={},
        kernel_version="0.11.0",
        package=None,
        manifest=None,
        active_plugins=[],
    )
    assert ctx.package is None
    assert ctx.manifest is None
    assert ctx.active_plugins == []


def test_agent_context_new_fields_are_optional():
    """New fields have defaults — existing callers are not broken."""
    ctx = AgentContext(
        agent_name="test",
        agent_id="test-id",
        evolution_mode="chaos",
        workspace_path=Path("/tmp/test"),
        config={},
        kernel_version="0.11.0",
    )
    assert ctx.package is None
    assert ctx.manifest is None
    assert ctx.active_plugins == []


# ---- Manifest tests (Task 2) ----

from tain_agent.package.manifest import (
    Manifest,
    ManifestPackage,
    ManifestInfra,
    ManifestCapability,
    ManifestCognitive,
    ManifestExpression,
    ArtifactEntry,
    ToolEntry,
    SkillEntry,
    parse_manifest,
    validate_manifest,
    ManifestValidationError,
)

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
        os.unlink(tmp_path)


def test_validate_manifest_missing_required():
    bad = {"package": {"name": "Test"}}
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


# ---- PackageRegistry tests (Task 3) ----


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


# ---- CLI handler tests (Task 4) ----

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
    assert result["ok"] is True
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
    assert bump_version("0.7.3", "cognitive/identity") == "0.8.0"
