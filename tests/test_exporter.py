"""Tests for the agent export pipeline."""

import pytest
import tempfile
from pathlib import Path
from unittest.mock import patch


class TestExportResult:
    def test_create(self):
        from tain_agent.evolution.exporter import ExportResult
        result = ExportResult(
            name="test_agent",
            version="0.1.0",
            output_path="/tmp/test.tar.gz",
            dist_dir="/tmp/test_dist",
            tool_count=3,
            knowledge_count=5,
        )
        assert result.name == "test_agent"
        assert result.dist_dir == "/tmp/test_dist"
        assert result.tool_count == 3


class TestVerifyExport:
    def test_missing_dir(self):
        from tain_agent.evolution.exporter import _verify_export
        result = _verify_export(Path("/nonexistent/export"))
        assert result["all_ok"] is False

    def test_empty_dir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            from tain_agent.evolution.exporter import _verify_export
            result = _verify_export(Path(tmpdir))
            assert isinstance(result, dict)
            assert "all_ok" in result


class TestExportPipeline:
    def test_pipeline_creation(self):
        from tain_agent.evolution.exporter import ExportPipeline
        pipeline = ExportPipeline()
        assert pipeline is not None

    def test_verify_in_empty_dist(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            dist = Path(tmpdir) / "export"
            dist.mkdir()
            (dist / "main.py").write_text("print('hello')")

            from tain_agent.evolution.exporter import _verify_export
            result = _verify_export(dist)
            assert isinstance(result, dict)
            assert "all_ok" in result
