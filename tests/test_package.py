import json
import os
import tempfile

import pytest
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
    # _runtime is not a valid LayerKind
    with pytest.raises(ValueError):
        LayerKind("_runtime")
    # _runtime value is not among layer values
    assert "_runtime" not in [layer.value for layer in LayerKind]


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
