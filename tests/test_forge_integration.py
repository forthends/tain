"""Integration tests for the complete forge cycle."""
import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


class TestForgeIntegration:
    """End-to-end tests of the forge subsystem."""

    def test_dependency_application_roundtrip(self, tmp_path):
        """Application report should be readable by external tools."""
        from tain_agent.evolution.dependency_manager import DependencyManager

        dm = DependencyManager(
            workspace_dir=str(tmp_path),
            allowed_packages=["requests"],
            decision_log=MagicMock(),
        )
        dm.resolve(
            tool_name="viz",
            packages=["plotly"],
            reason="需要交互式图表",
            alternative_considered="matplotlib 不足",
        )

        apps_file = tmp_path / "_forge_applications.jsonl"
        apps = [json.loads(line) for line in apps_file.read_text().strip().split("\n") if line]
        assert len(apps) == 1
        assert apps[0]["tool_name"] == "viz"
        assert apps[0]["status"] == "pending"
        # Reviewer can update status
        apps[0]["status"] = "approved"
        apps_file.write_text(
            "\n".join(json.dumps(a, ensure_ascii=False) for a in apps) + "\n"
        )
        apps2 = [json.loads(line) for line in apps_file.read_text().strip().split("\n") if line]
        assert apps2[0]["status"] == "approved"

    def test_run_test_integration_with_forged_tool(self, tmp_path):
        """run_test should work with code that matches typical forged tool output."""
        from tain_agent.tools.primal import run_test

        code = (
            "import json\n"
            "def main(query: str = 'test'):\n"
            "    return {'results': [1, 2, 3], 'query': query}\n"
        )
        with patch("tain_agent.tools.primal._WORKSPACE_DIR", Path(str(tmp_path))):
            result = run_test(
                test_target="search_tool",
                test_type="function",
                test_code=code,
            )
        assert result["passed"] is True

    def test_forge_tool_rejects_blacklisted_import(self):
        """ToolSandbox should reject code with os.system call."""
        from tain_agent.tools.forge import ToolForge
        from tain_agent.tools.registry import ToolRegistry

        registry = ToolRegistry()
        forge = ToolForge(registry)
        result = forge.forge(
            name="dangerous_tool",
            description="Should be blocked",
            code="import os\ndef main():\n    os.system('ls')\n    return 'done'",
        )
        assert result["success"] is False
        assert "rejected" in str(result.get("error", "")).lower()


class TestForgeUpdate:
    """Tests for the forge --update mode (action='update')."""

    CODE_V1 = (
        'import json\n'
        'def main():\n'
        '    return {"version": 1, "data": json.dumps([1, 2, 3])}\n'
    )
    CODE_V2 = (
        'import json\n'
        'def main():\n'
        '    return {"version": 2, "data": json.dumps([4, 5, 6])}\n'
    )

    def test_update_existing_tool(self, tmp_path):
        """Create a tool, then update it — the update should succeed and reflect new code."""
        from tain_agent.tools.forge import ToolForge
        from tain_agent.tools.registry import ToolRegistry

        registry = ToolRegistry()
        forge = ToolForge(registry, workspace_dir=str(tmp_path))

        # Step 1: create
        result = forge.forge(
            name="my_tool",
            description="Version 1",
            code=self.CODE_V1,
            action="create",
        )
        assert result["success"] is True
        assert "my_tool" in registry.list_names()

        # Step 2: update
        result = forge.forge(
            name="my_tool",
            description="Version 2",
            code=self.CODE_V2,
            action="update",
        )
        assert result["success"] is True

        # Step 3: verify the updated tool returns new data
        response = registry.call("my_tool")
        assert response["success"] is True
        output = response["result"]
        assert output["version"] == 2
        assert output["data"] == '[4, 5, 6]'

    def test_update_nonexistent_tool_rejected(self, tmp_path):
        """Updating a tool that doesn't exist should fail with a clear error."""
        from tain_agent.tools.forge import ToolForge
        from tain_agent.tools.registry import ToolRegistry

        registry = ToolRegistry()
        forge = ToolForge(registry, workspace_dir=str(tmp_path))

        result = forge.forge(
            name="ghost_tool",
            description="Does not exist",
            code=self.CODE_V1,
            action="update",
        )
        assert result["success"] is False
        assert "does not exist" in result["error"].lower()
        assert "create" in result.get("hint", "").lower()

    def test_update_creates_backup(self, tmp_path):
        """Updating a tool should create a .py.bak backup with the old content."""
        from tain_agent.tools.forge import ToolForge
        from tain_agent.tools.registry import ToolRegistry

        registry = ToolRegistry()
        forge = ToolForge(registry, workspace_dir=str(tmp_path))

        # Create first
        forge.forge(
            name="backup_tool",
            description="Original",
            code=self.CODE_V1,
            action="create",
        )

        # Update
        forge.forge(
            name="backup_tool",
            description="Updated",
            code=self.CODE_V2,
            action="update",
        )

        # Check .py.bak exists and contains old code
        bak_path = tmp_path / "capability" / "tools" / "backup_tool.py.bak"
        assert bak_path.exists()
        bak_content = bak_path.read_text(encoding="utf-8")
        assert "version\": 1" in bak_content

        # Current file should contain new code
        source_path = tmp_path / "capability" / "tools" / "backup_tool.py"
        source_content = source_path.read_text(encoding="utf-8")
        assert "version\": 2" in source_content

    def test_create_still_rejects_existing(self, tmp_path):
        """Default action='create' should still reject an existing tool name."""
        from tain_agent.tools.forge import ToolForge
        from tain_agent.tools.registry import ToolRegistry

        registry = ToolRegistry()
        forge = ToolForge(registry, workspace_dir=str(tmp_path))

        # Create first
        result = forge.forge(
            name="duplicate_tool",
            description="First",
            code=self.CODE_V1,
        )
        assert result["success"] is True

        # Try to create again with same name
        result = forge.forge(
            name="duplicate_tool",
            description="Second",
            code=self.CODE_V2,
        )
        assert result["success"] is False
        assert "already exists" in result["error"].lower()
        assert "update" in result.get("hint", "").lower()

    def test_invalid_action_rejected(self, tmp_path):
        """An invalid action value should return an error immediately."""
        from tain_agent.tools.forge import ToolForge
        from tain_agent.tools.registry import ToolRegistry

        registry = ToolRegistry()
        forge = ToolForge(registry, workspace_dir=str(tmp_path))

        result = forge.forge(
            name="some_tool",
            description="Test",
            code=self.CODE_V1,
            action="delete",
        )
        assert result["success"] is False
        assert "invalid action" in result["error"].lower()
        assert "create" in result["error"].lower()
        assert "update" in result["error"].lower()
