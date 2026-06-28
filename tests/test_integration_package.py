# tests/test_integration_package.py
"""Integration test: create package → load with AgentRuntime → verify structure."""

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
