"""Tests for evolution pipeline — ImprovementSpec and StageResult."""

import pytest
import time

from tain_agent.evolution.pipeline import ImprovementSpec, StageResult


class TestImprovementSpec:
    """Tests for ImprovementSpec — the specification data class."""

    def test_create_with_required_fields(self):
        """An ImprovementSpec must accept capability_id and description as required fields."""
        spec = ImprovementSpec(
            capability_id="test_cap",
            description="A test capability improvement",
        )
        assert spec.capability_id == "test_cap"
        assert spec.description == "A test capability improvement"
        assert spec.created_at is not None

    def test_to_dict_includes_all_fields(self):
        """to_dict() should include every field defined in the spec."""
        spec = ImprovementSpec(
            capability_id="cap_1",
            description="Improve logging",
            tool_name="better_logger",
            tool_description="Enhanced logger tool",
            design_notes="Add structured logging",
            success_test="assert logger.has_level('DEBUG')",
            priority="HIGH",
        )
        d = spec.to_dict()
        expected_keys = {
            "capability_id", "description", "tool_name",
            "tool_description", "design_notes", "success_test",
            "priority", "created_at",
        }
        assert expected_keys == set(d.keys())
        assert d["capability_id"] == "cap_1"
        assert d["description"] == "Improve logging"
        assert d["tool_name"] == "better_logger"
        assert d["tool_description"] == "Enhanced logger tool"
        assert d["design_notes"] == "Add structured logging"
        assert d["success_test"] == "assert logger.has_level('DEBUG')"
        assert d["priority"] == "HIGH"

    def test_empty_tool_name_defaults_to_empty_string(self):
        """When tool_name is omitted it should default to ''."""
        spec = ImprovementSpec(capability_id="x", description="y")
        assert spec.tool_name == ""
        d = spec.to_dict()
        assert d["tool_name"] == ""

    def test_unicode_description_works(self):
        """ImprovementSpec should support Unicode descriptions (e.g. Chinese characters)."""
        spec = ImprovementSpec(
            capability_id="cn_cap",
            description="支持中文描述的改进能力 — 增强多语言支持。",
        )
        assert "中文" in spec.description
        assert "多语言" in spec.description
        # to_dict should round-trip the unicode without corruption
        d = spec.to_dict()
        assert "中文" in d["description"]

    def test_multiple_specs_have_independent_created_at(self):
        """Each spec should get its own created_at timestamp; they should differ
        when created in sequence with a sleep between them."""
        spec_a = ImprovementSpec(capability_id="a", description="first")
        time.sleep(0.01)
        spec_b = ImprovementSpec(capability_id="b", description="second")
        # Two specs created at different times should have different timestamps
        assert spec_a.created_at != spec_b.created_at

    def test_priority_defaults_to_MEDIUM(self):
        """The default priority should be 'MEDIUM'."""
        spec = ImprovementSpec(capability_id="x", description="y")
        assert spec.priority == "MEDIUM"

    def test_to_dict_returns_correct_types(self):
        """All to_dict values should be basic JSON-serializable types."""
        spec = ImprovementSpec(capability_id="cap_x", description="desc")
        d = spec.to_dict()
        for key, value in d.items():
            assert isinstance(value, (str, int, float, bool, type(None), list, dict)), \
                f"Key '{key}' has non-serializable type: {type(value)}"


class TestStageResult:
    """Tests for StageResult — a single pipeline stage execution result."""

    def test_starts_not_passed(self):
        """A freshly created StageResult should NOT be passed."""
        stage = StageResult("analyze")
        assert stage.passed is False
        assert stage.stage_name == "analyze"
        assert stage.output is None
        assert stage.error is None
        assert stage.completed_at is None

    def test_can_be_marked_passed(self):
        """complete(passed=True) should mark the stage as passed and set completed_at."""
        stage = StageResult("design")
        assert stage.passed is False
        result = stage.complete(passed=True, output={"tool": "logger"})
        assert result is stage  # complete() returns self for chaining
        assert stage.passed is True
        assert stage.output == {"tool": "logger"}
        assert stage.completed_at is not None

    def test_can_be_marked_failed(self):
        """complete(passed=False) should keep passed=False."""
        stage = StageResult("forge")
        stage.complete(passed=False)
        assert stage.passed is False
        assert stage.completed_at is not None

    def test_captures_error(self):
        """When an error string is provided, it should be stored in the error field."""
        stage = StageResult("verify")
        stage.complete(passed=False, error="Sandbox rejected import: os")
        assert stage.error == "Sandbox rejected import: os"
        assert stage.passed is False

    def test_metadata_stored_in_complete(self):
        """Extra keyword arguments to complete() should be stored in metadata dict."""
        stage = StageResult("register")
        stage.complete(passed=True, tool_name="hammer", version="1.0")
        assert stage.metadata == {"tool_name": "hammer", "version": "1.0"}

    def test_to_dict_truncates_long_output(self):
        """to_dict() should truncate output strings longer than 500 chars."""
        stage = StageResult("analyze")
        long_output = "x" * 600
        stage.complete(passed=True, output=long_output)
        d = stage.to_dict()
        assert len(d["output"]) <= 500
        # After truncation it should be at most 500 chars
        assert d["output"] == long_output[:500]

    def test_to_dict_serializes_non_string_output(self):
        """to_dict() should str() non-string output values."""
        stage = StageResult("analyze")
        # Output that is not a string (e.g. a dict) should be str()'d
        output_dict = {"key": "value", "nested": [1, 2, 3]}
        stage.complete(passed=True, output=output_dict)
        d = stage.to_dict()
        assert isinstance(d["output"], str)
        assert "key" in d["output"]

    def test_to_dict_keys(self):
        """to_dict() should return expected keys even for a pending stage."""
        stage = StageResult("analyze")
        d = stage.to_dict()
        expected_keys = {"stage", "passed", "output", "error", "metadata",
                         "started_at", "completed_at"}
        assert expected_keys == set(d.keys())
        assert d["stage"] == "analyze"
        assert d["passed"] is False
        assert d["completed_at"] is None
