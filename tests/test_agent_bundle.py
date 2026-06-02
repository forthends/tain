import tempfile
from pathlib import Path
from tain_agent.evolution.skill_exporter import export_agent_bundle

class TestAgentBundle:
    def test_export_creates_skill_md(self):
        with tempfile.TemporaryDirectory() as d:
            r = export_agent_bundle("test_agent", output_dir=d)
            assert Path(r["bundle_path"]).exists()
            assert (Path(r["bundle_path"]) / "SKILL.md").exists()
    def test_export_creates_references_dir(self):
        with tempfile.TemporaryDirectory() as d:
            r = export_agent_bundle("test_agent", output_dir=d)
            assert (Path(r["bundle_path"]) / "references").exists()
    def test_export_creates_scripts_dir(self):
        with tempfile.TemporaryDirectory() as d:
            r = export_agent_bundle("test_agent", output_dir=d)
            assert (Path(r["bundle_path"]) / "scripts").exists()
    def test_export_handles_nonexistent_agent(self):
        r = export_agent_bundle("nonexistent_agent_xyz", output_dir="/tmp/tain_test")
        assert "bundle_path" in r
