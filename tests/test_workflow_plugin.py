"""Tests for WorkflowPlugin — DAG engine and plugin integration."""

import tempfile
from pathlib import Path

import pytest

from tain_agent.kernel.protocol import AgentContext, PluginProtocol
from tain_agent.plugins.workflow import WorkflowPlugin
from tain_agent.plugins.workflow.engine import (
    Workflow,
    WorkflowState,
    WorkflowStep,
    StepResult,
    StepType,
    RetryPolicy,
)


class TestWorkflowEngine:
    """Tests for the Workflow DAG engine — topological order, parallel groups,
    cycle detection, unknown dependency detection."""

    def test_linear_topological_order(self):
        """A → B → C should produce linear order."""
        wf = Workflow(name="linear", steps=[
            WorkflowStep(name="A", depends_on=[]),
            WorkflowStep(name="B", depends_on=["A"]),
            WorkflowStep(name="C", depends_on=["B"]),
        ])
        order = wf.topological_order()
        assert order == ["A", "B", "C"]

    def test_parallel_groups(self):
        """Independent branches should form parallel groups."""
        wf = Workflow(name="parallel", steps=[
            WorkflowStep(name="init", depends_on=[]),
            WorkflowStep(name="task_a", depends_on=["init"]),
            WorkflowStep(name="task_b", depends_on=["init"]),
            WorkflowStep(name="merge", depends_on=["task_a", "task_b"]),
        ])
        groups = wf.parallel_groups()
        assert len(groups) == 3  # depth 0, 1, 2

        # Depth 0: init alone
        assert groups[0] == ["init"]

        # Depth 1: task_a and task_b can run in parallel
        assert set(groups[1]) == {"task_a", "task_b"}

        # Depth 2: merge alone
        assert groups[2] == ["merge"]

    def test_cycle_detection(self):
        """A → B → A should raise ValueError."""
        wf = Workflow(name="cyclic", steps=[
            WorkflowStep(name="A", depends_on=["B"]),
            WorkflowStep(name="B", depends_on=["A"]),
        ])
        with pytest.raises(ValueError, match="Cycle detected"):
            wf.topological_order()

    def test_unknown_dependency_detection(self):
        """Dependency on non-existent step should be detected by validate."""
        wf = Workflow(name="bad", steps=[
            WorkflowStep(name="A", depends_on=["nonexistent"]),
        ])
        errors = wf.validate()
        assert len(errors) == 1
        assert "nonexistent" in errors[0]

    def test_duplicate_step_name_detection(self):
        wf = Workflow(name="dup", steps=[
            WorkflowStep(name="A"),
            WorkflowStep(name="A"),
        ])
        errors = wf.validate()
        assert any("Duplicate" in e for e in errors)

    def test_single_step_workflow(self):
        wf = Workflow(name="single", steps=[
            WorkflowStep(name="only"),
        ])
        assert wf.topological_order() == ["only"]
        groups = wf.parallel_groups()
        assert groups == [["only"]]

    def test_diamond_topology(self):
        """A → B, A → C, B → D, C → D"""
        wf = Workflow(name="diamond", steps=[
            WorkflowStep(name="A", depends_on=[]),
            WorkflowStep(name="B", depends_on=["A"]),
            WorkflowStep(name="C", depends_on=["A"]),
            WorkflowStep(name="D", depends_on=["B", "C"]),
        ])
        order = wf.topological_order()
        assert order[0] == "A"
        assert order[-1] == "D"
        assert set(order[1:3]) == {"B", "C"}


class TestWorkflowPlugin:
    """Tests for the WorkflowPlugin itself."""

    def _make_ctx(self, tmpdir):
        return AgentContext(
            agent_name="test",
            agent_id="w1",
            evolution_mode="chaos",
            workspace_path=Path(tmpdir),
            config={},
            kernel_version="0.6.0",
        )

    def test_satisfies_protocol(self):
        assert isinstance(WorkflowPlugin(), PluginProtocol)

    def test_create_and_start_workflow(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            ctx = self._make_ctx(tmpdir)
            plugin = WorkflowPlugin()
            plugin.initialize(ctx)

            wf = plugin.create("test_wf", "A test workflow", [
                {"name": "step1", "description": "First step", "step_type": "tool"},
                {"name": "step2", "description": "Second step", "depends_on": ["step1"]},
            ])
            assert wf.state == WorkflowState.PENDING

            started = plugin.start("test_wf")
            assert started is not None
            assert started.state == WorkflowState.RUNNING

            plugin.shutdown()

    def test_validate_rejects_cycle(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            ctx = self._make_ctx(tmpdir)
            plugin = WorkflowPlugin()
            plugin.initialize(ctx)

            with pytest.raises(ValueError, match="validation failed"):
                plugin.create("cyclic", "A cycle", [
                    {"name": "A", "depends_on": ["B"]},
                    {"name": "B", "depends_on": ["A"]},
                ])

            plugin.shutdown()

    def test_pause_and_resume(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            ctx = self._make_ctx(tmpdir)
            plugin = WorkflowPlugin()
            plugin.initialize(ctx)

            plugin.create("test_wf", "Test", [
                {"name": "step1", "step_type": "tool"},
            ])
            plugin.start("test_wf")

            paused = plugin.pause("test_wf")
            assert paused.state == WorkflowState.PAUSED

            resumed = plugin.resume("test_wf")
            assert resumed.state == WorkflowState.RUNNING

            plugin.shutdown()

    def test_status_shows_topological_info(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            ctx = self._make_ctx(tmpdir)
            plugin = WorkflowPlugin()
            plugin.initialize(ctx)

            plugin.create("test_wf", "Test", [
                {"name": "init", "step_type": "tool"},
                {"name": "process", "step_type": "tool", "depends_on": ["init"]},
            ])
            s = plugin.status("test_wf")
            assert s is not None
            assert s["name"] == "test_wf"
            assert "topological_order" in s
            assert "parallel_groups" in s
            assert s["state"] == "pending"

            plugin.shutdown()

    def test_status_all(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            ctx = self._make_ctx(tmpdir)
            plugin = WorkflowPlugin()
            plugin.initialize(ctx)

            plugin.create("wf1", "First", [{"name": "s1"}])
            plugin.create("wf2", "Second", [{"name": "s1"}])
            all_status = plugin.status_all()
            assert len(all_status) == 2

            plugin.shutdown()

    def test_advance_records_step_result(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            ctx = self._make_ctx(tmpdir)
            plugin = WorkflowPlugin()
            plugin.initialize(ctx)

            plugin.create("test_wf", "Test", [
                {"name": "step1", "step_type": "tool"},
            ])
            result = StepResult(step_name="step1", success=True, output="done")
            assert plugin.advance(result) is True

            s = plugin.status("test_wf")
            assert s["state"] == "completed"

            plugin.shutdown()

    def test_plan_from_goal_simple(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            ctx = self._make_ctx(tmpdir)
            plugin = WorkflowPlugin()
            plugin.initialize(ctx)

            wf = plugin.plan_from_goal("Deploy the application")
            assert wf is not None
            assert len(wf.steps) >= 1
            assert wf.state == WorkflowState.PENDING

            plugin.shutdown()

    def test_persistence_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            ctx = self._make_ctx(tmpdir)
            plugin = WorkflowPlugin()
            plugin.initialize(ctx)

            plugin.create("persist_wf", "Persist test", [
                {"name": "s1", "step_type": "tool"},
                {"name": "s2", "step_type": "llm", "depends_on": ["s1"]},
            ])
            plugin.shutdown()

            # Reload
            plugin2 = WorkflowPlugin()
            plugin2.initialize(ctx)
            assert "persist_wf" in plugin2._workflows
            reloaded = plugin2._workflows["persist_wf"]
            assert len(reloaded.steps) == 2
            plugin2.shutdown()
