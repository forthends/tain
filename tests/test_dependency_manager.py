"""Tests for DependencyManager."""
import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Ensure project root on path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tain_agent.evolution.dependency_manager import DependencyManager, ResolveResult


class TestDependencyManagerResolve:
    """Test resolve() — the core dependency resolution logic."""

    def test_allowed_package_returns_installed(self, tmp_path):
        """Package in allowlist should be marked installed."""
        dm = DependencyManager(
            workspace_dir=str(tmp_path),
            allowed_packages=["requests"],
            decision_log=MagicMock(),
        )
        with patch.object(dm, "_pip_install", return_value=True) as mock_install:
            result = dm.resolve(tool_name="test_tool", packages=["requests>=2.28"])
        assert isinstance(result, ResolveResult)
        assert "requests" in result.installed
        assert result.rejected == []
        mock_install.assert_called_once()

    def test_disallowed_package_returns_rejected_and_writes_application(self, tmp_path):
        """Package NOT in allowlist should be rejected and application written."""
        dm = DependencyManager(
            workspace_dir=str(tmp_path),
            allowed_packages=["requests"],
            decision_log=MagicMock(),
        )
        result = dm.resolve(tool_name="test_tool", packages=["unknown-pkg"])
        assert "unknown-pkg" in result.rejected
        assert result.installed == []

        applications_file = tmp_path / "_forge_applications.jsonl"
        assert applications_file.exists()
        apps = [json.loads(line) for line in applications_file.read_text().strip().split("\n") if line]
        assert len(apps) == 1
        assert apps[0]["package"] == "unknown-pkg"
        assert apps[0]["tool_name"] == "test_tool"
        assert apps[0]["status"] == "pending"

    def test_mixed_allowed_and_disallowed(self, tmp_path):
        """Mixed packages: allowed installed, disallowed rejected."""
        dm = DependencyManager(
            workspace_dir=str(tmp_path),
            allowed_packages=["requests", "pandas"],
            decision_log=MagicMock(),
        )
        with patch.object(dm, "_pip_install", return_value=True):
            result = dm.resolve(
                tool_name="viz_tool",
                packages=["requests>=2.28", "secret-pkg"],
            )
        assert "requests" in result.installed
        assert "secret-pkg" in result.rejected

    def test_already_installed_package_skipped(self, tmp_path):
        """Already-installed package should be skipped without re-install."""
        dm = DependencyManager(
            workspace_dir=str(tmp_path),
            allowed_packages=["requests"],
            decision_log=MagicMock(),
        )
        with patch.object(dm, "_pip_install", return_value=True) as mock_install:
            dm.resolve(tool_name="tool_a", packages=["requests"])
            assert mock_install.call_count == 1
            dm.resolve(tool_name="tool_b", packages=["requests"])
            # Second call should skip — already installed
            assert mock_install.call_count == 1

    def test_empty_packages_list(self, tmp_path):
        """Empty dependency list should return success with no installs."""
        dm = DependencyManager(
            workspace_dir=str(tmp_path),
            allowed_packages=["requests"],
            decision_log=MagicMock(),
        )
        result = dm.resolve(tool_name="simple_tool", packages=[])
        assert result.installed == []
        assert result.rejected == []

    def test_application_file_contains_reason_and_alternative(self, tmp_path):
        """Application JSONL should include reason and alternative fields."""
        dm = DependencyManager(
            workspace_dir=str(tmp_path),
            allowed_packages=["requests"],
            decision_log=MagicMock(),
        )
        dm.resolve(
            tool_name="data_tool",
            packages=["plotly"],
            reason="需要交互式图表展示数据",
            alternative_considered="matplotlib 功能不足",
        )
        applications_file = tmp_path / "_forge_applications.jsonl"
        apps = [json.loads(line) for line in applications_file.read_text().strip().split("\n") if line]
        assert apps[0]["reason"] == "需要交互式图表展示数据"
        assert apps[0]["alternative_considered"] == "matplotlib 功能不足"


class TestDependencyManagerUninstallOrphans:
    """Test uninstall_orphans — cleanup when tools are removed."""

    def test_uninstall_shared_dependency_preserved(self, tmp_path):
        """Shared dependency used by another tool should not be removed."""
        dm = DependencyManager(
            workspace_dir=str(tmp_path),
            allowed_packages=["requests"],
            decision_log=MagicMock(),
        )
        with patch.object(dm, "_pip_install", return_value=True):
            dm.resolve(tool_name="tool_a", packages=["requests"])
            dm.resolve(tool_name="tool_b", packages=["requests"])
        orphans = dm.uninstall_orphans("tool_a")
        assert "requests" not in orphans  # still used by tool_b

    def test_uninstall_exclusive_dependency_removed(self, tmp_path):
        """Dependency used only by removed tool should be listed as orphan."""
        dm = DependencyManager(
            workspace_dir=str(tmp_path),
            allowed_packages=["requests", "pandas"],
            decision_log=MagicMock(),
        )
        with patch.object(dm, "_pip_install", return_value=True):
            dm.resolve(tool_name="tool_only", packages=["pandas"])
        orphans = dm.uninstall_orphans("tool_only")
        assert "pandas" in orphans
