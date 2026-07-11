# tests/test_agent_runtime.py
import hashlib
import json
import pytest
from pathlib import Path
from tain_agent.package import AgentPackage, PackageKind, PackageRegistry
from tain_agent.package.manifest import create_manifest, PackageIntegrityError
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


def test_runtime_rejects_hash_mismatch(tmp_path):
    """AgentRuntime should refuse to start if a declared file hash doesn't match."""
    packages_dir = tmp_path / "packages"
    packages_dir.mkdir()
    reg = PackageRegistry(packages_root=packages_dir)
    reg.create(name="HashFail", kind=PackageKind.AGENT, version="0.1.0")

    # Write a tool file with known content
    tool_dir = packages_dir / "HashFail" / "capability" / "tools"
    tool_path = tool_dir / "broken_tool.py"
    tool_path.write_text("def broken(): return 42\n")

    # Write manifest with a WRONG hash
    manifest_path = packages_dir / "HashFail" / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["capability"]["tools"].append({
        "name": "broken_tool",
        "version": "1.0.0",
        "path": "capability/tools/broken_tool.py",
        "hash": "sha256:0000000000000000000000000000000000000000000000000000000000000000",
    })
    manifest_path.write_text(json.dumps(manifest, indent=2))

    pkg = AgentPackage(name="HashFail", kind=PackageKind.AGENT,
                       version="0.1.0", packages_root=packages_dir)

    with pytest.raises((PackageIntegrityError, RuntimeError)) as exc:
        AgentRuntime(package=pkg, config={"agent": {"evolution_mode": "chaos"}})
    exc_msg = str(exc.value).lower()
    assert "integrity" in exc_msg or "hash" in exc_msg


def test_runtime_loads_valid_package(tmp_path):
    """AgentRuntime should start when hashes match."""
    packages_dir = tmp_path / "packages"
    packages_dir.mkdir()
    reg = PackageRegistry(packages_root=packages_dir)
    reg.create(name="ValidHash", kind=PackageKind.AGENT, version="0.1.0")

    # Write a tool file
    tool_dir = packages_dir / "ValidHash" / "capability" / "tools"
    tool_path = tool_dir / "good_tool.py"
    tool_path.write_text("def good(): return 42\n")

    # Write manifest with CORRECT hash
    correct_hash = "sha256:" + hashlib.sha256(tool_path.read_bytes()).hexdigest()
    manifest_path = packages_dir / "ValidHash" / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["capability"]["tools"].append({
        "name": "good_tool",
        "version": "1.0.0",
        "path": "capability/tools/good_tool.py",
        "hash": correct_hash,
    })
    manifest["infra"]["plugins"] = {}
    manifest_path.write_text(json.dumps(manifest, indent=2))

    pkg = AgentPackage(name="ValidHash", kind=PackageKind.AGENT,
                       version="0.1.0", packages_root=packages_dir)
    runtime = AgentRuntime(package=pkg, config={"agent": {"evolution_mode": "chaos"}})
    assert runtime is not None
