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
