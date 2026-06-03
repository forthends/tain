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
