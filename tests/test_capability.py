"""Tests for the capability registry."""

import pytest
from tain_agent.evolution.capability import CapabilityRegistry, DESIRED_CAPABILITIES
from tain_agent.tools.registry import ToolRegistry


class TestCapabilityRegistry:
    def test_init(self):
        cr = CapabilityRegistry()
        assert cr._custom_capabilities == {}

    def test_assess_without_registry(self):
        cr = CapabilityRegistry()
        result = cr.assess()
        assert "by_tier" in result
        assert "capabilities_covered" in result

    def test_assess_with_tools(self):
        tr = ToolRegistry()
        tr.register("web_search", lambda: None, "Search the web")
        cr = CapabilityRegistry(tool_registry=tr)
        result = cr.assess()
        assert "by_tier" in result
        # With some tools registered, coverage should be measurable
        assert isinstance(result["capabilities_covered"], int)

    def test_register_custom_capability(self):
        cr = CapabilityRegistry()
        cr._custom_capabilities["custom.test"] = {
            "tier": "CORE",
            "required_tools": ["my_tool"],
            "description": "Test capability",
        }
        assert "custom.test" in cr._custom_capabilities


class TestDesiredCapabilities:
    def test_is_non_empty_dict(self):
        assert isinstance(DESIRED_CAPABILITIES, dict)
        assert len(DESIRED_CAPABILITIES) > 0

    def test_each_capability_has_tier(self):
        for cap_name, cap_def in DESIRED_CAPABILITIES.items():
            assert "tier" in cap_def, f"{cap_name} missing tier"
            assert cap_def["tier"] in ("CORE", "EXTENDED", "ADVANCED", "FRONTIER")

    def test_each_capability_has_required_tools(self):
        for cap_name, cap_def in DESIRED_CAPABILITIES.items():
            required = cap_def.get("required_tools", [])
            assert isinstance(required, list), f"{cap_name} required_tools not a list"

    def test_has_core_capabilities(self):
        core_caps = [
            name for name, cap in DESIRED_CAPABILITIES.items()
            if cap.get("tier") == "CORE"
        ]
        assert len(core_caps) > 0
