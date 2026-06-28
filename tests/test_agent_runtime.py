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

    # Ensure directories that real plugins need
    (pkg.path / "identity").mkdir(parents=True, exist_ok=True)
    (pkg.path / "memory").mkdir(parents=True, exist_ok=True)
    (pkg.path / "logs").mkdir(parents=True, exist_ok=True)

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

    # Ensure directories that real plugins need
    (pkg.path / "identity").mkdir(parents=True, exist_ok=True)
    (pkg.path / "memory").mkdir(parents=True, exist_ok=True)
    (pkg.path / "logs").mkdir(parents=True, exist_ok=True)

    runtime = AgentRuntime(package=pkg, config=config)

    active_names = [p.__class__.__name__ for p in runtime.active_plugins]
    assert "ToolPlugin" in active_names


def test_agent_runtime_shutdown(tmp_path):
    packages_dir = tmp_path / "packages"
    packages_dir.mkdir()
    reg = PackageRegistry(packages_root=packages_dir)
    pkg = reg.create(name="TestShutdown", kind=PackageKind.AGENT, version="0.1.0")
    config = {"llm": {"provider": "test"}}

    # Ensure directories that real plugins need
    (pkg.path / "identity").mkdir(parents=True, exist_ok=True)
    (pkg.path / "memory").mkdir(parents=True, exist_ok=True)
    (pkg.path / "logs").mkdir(parents=True, exist_ok=True)

    runtime = AgentRuntime(package=pkg, config=config)
    runtime.shutdown()
    # No exception = success


def test_agent_runtime_get_plugin(tmp_path):
    packages_dir = tmp_path / "packages"
    packages_dir.mkdir()
    reg = PackageRegistry(packages_root=packages_dir)
    pkg = reg.create(name="TestGetPlugin", kind=PackageKind.AGENT, version="0.1.0")
    config = {"llm": {"provider": "test"}}

    # Ensure directories that real plugins need
    (pkg.path / "identity").mkdir(parents=True, exist_ok=True)
    (pkg.path / "memory").mkdir(parents=True, exist_ok=True)
    (pkg.path / "logs").mkdir(parents=True, exist_ok=True)

    runtime = AgentRuntime(package=pkg, config=config)

    identity = runtime.get_identity()
    assert identity is not None
    memory = runtime.get_memory()
    assert memory is not None
    # tool not declared, should be None
    tool = runtime.get_plugin("ToolPlugin")
    assert tool is None


def test_agent_runtime_health_check(tmp_path):
    packages_dir = tmp_path / "packages"
    packages_dir.mkdir()
    reg = PackageRegistry(packages_root=packages_dir)
    pkg = reg.create(name="TestHealth", kind=PackageKind.AGENT, version="0.1.0")
    config = {"llm": {"provider": "test"}}

    # Ensure directories that real plugins need
    (pkg.path / "identity").mkdir(parents=True, exist_ok=True)
    (pkg.path / "memory").mkdir(parents=True, exist_ok=True)
    (pkg.path / "logs").mkdir(parents=True, exist_ok=True)

    runtime = AgentRuntime(package=pkg, config=config)
    results = runtime.health_check()
    assert "IdentityPlugin" in results
    assert "MemoryPlugin" in results
