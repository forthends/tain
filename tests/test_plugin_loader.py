# tests/test_plugin_loader.py
import pytest
from tain_agent.runtime.plugin_loader import PluginLoader, PluginVersionError, semver_match
from tain_agent.kernel.protocol import AgentContext, HealthStatus
from tain_agent.kernel.dispatch import Dispatch, RouteNotFound
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


def test_semver_match_exact():
    assert semver_match("1.2.0", "1.2.0") is True
    assert semver_match("1.2.1", "1.2.0") is False


def test_semver_match_caret():
    # >=1.0.0: caret allows same-major, higher-or-equal minor+patch
    assert semver_match("1.2.0", "^1.2.0") is True
    assert semver_match("1.2.5", "^1.2.0") is True
    assert semver_match("1.2.0", "^1.2.5") is False  # patch too low
    assert semver_match("1.9.0", "^1.2.0") is True
    assert semver_match("2.0.0", "^1.2.0") is False


def test_semver_match_caret_zero_major():
    # Semver spec: for 0.y.z, caret = tilde (^0.2.0 means >=0.2.0, <0.3.0)
    assert semver_match("0.2.0", "^0.2.0") is True
    assert semver_match("0.2.5", "^0.2.0") is True
    assert semver_match("0.2.0", "^0.2.5") is False  # patch too low
    assert semver_match("0.3.0", "^0.2.0") is False  # minor bump → breaking
    assert semver_match("0.9.9", "^0.2.0") is False  # minor bump → breaking
    assert semver_match("1.0.0", "^0.9.0") is False  # major bump


def test_semver_match_tilde():
    assert semver_match("1.2.0", "~1.2.0") is True
    assert semver_match("1.2.9", "~1.2.0") is True
    assert semver_match("1.3.0", "~1.2.0") is False


def test_plugin_loader_perpetual_plugins(loader, ctx):
    """Identity and Memory are always loaded, even with empty manifest declaration."""
    manifest_plugins = {}
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


def test_route_not_found_raises():
    d = Dispatch()
    with pytest.raises(RouteNotFound) as exc:
        d.call("nonexistent.route")
    assert "nonexistent.route" in str(exc.value)
    assert exc.value.event == "nonexistent.route"


def test_call_or_none_returns_none_for_missing_route():
    d = Dispatch()
    result = d.call_or_none("nonexistent.route")
    assert result is None


def test_call_or_none_returns_value_for_registered_route():
    d = Dispatch()
    d.register("test.echo", lambda x: x)
    result = d.call_or_none("test.echo", "hello")
    assert result == "hello"


def test_call_still_works_for_registered_routes():
    d = Dispatch()
    d.register("test.add", lambda a, b: a + b)
    result = d.call("test.add", 1, 2)
    assert result == 3
