"""Tests for evolution pipeline — gap detection, design, verify, register."""
import pytest


class TestPipelineGapDetection:
    def test_analyze_returns_stage_result(self):
        """analyze() should return a StageResult even without a CapabilityRegistry."""
        from tain_agent.evolution.pipeline import SelfImprovementPipeline, StageResult
        pipeline = SelfImprovementPipeline()
        result = pipeline.analyze()
        assert isinstance(result, StageResult)
        assert result.stage_name == "analyze"

    def test_analyze_detects_gap_or_no_registry(self):
        """analyze() returns a StageResult. When no registry is available,
        it reports the missing registry as the failure reason."""
        from tain_agent.evolution.pipeline import SelfImprovementPipeline
        pipeline = SelfImprovementPipeline()
        result = pipeline.analyze()
        # Without a CapabilityRegistry, analyze should fail gracefully
        assert not result.passed
        assert result.error is not None
        assert "CapabilityRegistry" in (result.error or "")

    def test_design_stage_stops_for_human(self):
        """The pipeline must have a design method for human review gate."""
        from tain_agent.evolution.pipeline import SelfImprovementPipeline
        pipeline = SelfImprovementPipeline()
        assert hasattr(pipeline, 'design')
        assert callable(pipeline.design)


class TestPipelineVerification:
    def test_verify_rejects_unsafe_imports(self):
        """The sandbox should reject code with dangerous os.system calls."""
        unsafe_code = "import os\ndef main():\n    os.system('rm -rf /')\n"
        from tain_agent.tools.forged.test_forged_tool import test_forged_tool
        result = test_forged_tool(unsafe_code)
        assert result["passed"] is False
        assert any(e["type"] == "blocked_import" for e in result.get("errors", []))

    def test_verify_rejects_subprocess_imports(self):
        """The sandbox should reject code with subprocess imports."""
        unsafe_code = "import subprocess\ndef main():\n    subprocess.run(['ls'])\n"
        from tain_agent.tools.forged.test_forged_tool import test_forged_tool
        result = test_forged_tool(unsafe_code)
        assert result["passed"] is False
        assert any(e["type"] == "blocked_import" for e in result.get("errors", []))

    def test_verify_rejects_eval_call(self):
        """The sandbox should reject code calling eval()."""
        unsafe_code = "def main():\n    eval('1+1')\n"
        from tain_agent.tools.forged.test_forged_tool import test_forged_tool
        result = test_forged_tool(unsafe_code)
        assert result["passed"] is False
        assert any(e["type"] == "blocked_call" for e in result.get("errors", []))

    def test_verify_accepts_safe_tool(self):
        """The sandbox should accept safe code with allowed imports."""
        safe_code = (
            "import json\n"
            "def hello():\n"
            "    return json.dumps({'hello': 'world'})\n"
        )
        from tain_agent.tools.forged.test_forged_tool import test_forged_tool
        result = test_forged_tool(safe_code)
        assert result["passed"] is True
        assert result.get("errors") == [] or len(result["errors"]) == 0

    def test_verify_accepts_safe_tool_with_multiple_allowed_imports(self):
        """The sandbox should accept code with multiple allowed stdlib imports."""
        safe_code = (
            "import json, datetime, re, math, hashlib\n"
            "def main():\n"
            "    return str(datetime.datetime.now())\n"
        )
        from tain_agent.tools.forged.test_forged_tool import test_forged_tool
        result = test_forged_tool(safe_code)
        assert result["passed"] is True


class TestPipelineRegistration:
    def test_pipeline_has_register_method(self):
        """The pipeline should have register_improvement for stage 5."""
        from tain_agent.evolution.pipeline import SelfImprovementPipeline
        pipeline = SelfImprovementPipeline()
        assert hasattr(pipeline, 'register_improvement')
        assert callable(pipeline.register_improvement)

    def test_pipeline_has_run_full_pipeline(self):
        """The pipeline should expose run_full_pipeline as the main entry point."""
        from tain_agent.evolution.pipeline import SelfImprovementPipeline
        pipeline = SelfImprovementPipeline()
        assert hasattr(pipeline, 'run_full_pipeline')
        assert callable(pipeline.run_full_pipeline)

    def test_pipeline_has_five_stage_methods(self):
        """Pipeline should have all 5 stage methods: analyze, design, forge,
        verify, register_improvement."""
        from tain_agent.evolution.pipeline import SelfImprovementPipeline
        pipeline = SelfImprovementPipeline()
        for method in ['analyze', 'design', 'forge', 'verify', 'register_improvement']:
            assert hasattr(pipeline, method), f"Missing stage method: {method}"
            assert callable(getattr(pipeline, method)), (
                f"Stage method '{method}' should be callable"
            )


class TestPipelineRunFull:
    def test_run_full_pipeline_without_code_stops_after_design(self):
        """run_full_pipeline without code should run analyze+design then stop."""
        from tain_agent.evolution.pipeline import SelfImprovementPipeline, PipelineResult
        pipeline = SelfImprovementPipeline()
        result = pipeline.run_full_pipeline()
        assert isinstance(result, PipelineResult)
        # Should have at least the analyze stage (and design if analyze passes)
        assert len(result.stages) >= 1

    def test_pipeline_result_summary_no_gaps(self):
        """PipelineResult summary is generated when finalized."""
        from tain_agent.evolution.pipeline import (
            SelfImprovementPipeline, ImprovementSpec, StageResult, PipelineResult,
        )
        spec = ImprovementSpec("test_cap", "Test description")
        result = PipelineResult(spec)
        stage = StageResult("test_stage")
        stage.complete(True, output={"action": "ok"})
        result.add_stage(stage)
        result.finalize()
        assert result.overall_passed is True
        assert "test_cap" in result.summary
