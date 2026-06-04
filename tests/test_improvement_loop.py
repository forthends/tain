"""Tests for the improvement loop trigger system."""
import pytest
from tain_agent.evolution.improvement_loop import ImprovementLoop
from tain_agent.evolution.goal import GoalSystem


class FakeDecisionLog:
    def __init__(self, entries=None):
        self._entries = entries or []

    def read_all(self):
        return list(self._entries)


class TestUserValueDimensions:
    def test_task_completion_returns_zero_when_no_data(self):
        loop = ImprovementLoop(decision_log=FakeDecisionLog())
        score = loop._eval_task_completion(0.30)
        assert score == 0.0

    def test_task_completion_with_failures(self):
        entries = [
            {"decision_type": "task_outcome", "actual_outcome": "success"},
            {"decision_type": "task_outcome", "actual_outcome": "failure"},
            {"decision_type": "task_outcome", "actual_outcome": "failure"},
            {"decision_type": "task_outcome", "actual_outcome": "success"},
            {"decision_type": "other", "actual_outcome": "ignored"},
        ]
        loop = ImprovementLoop(decision_log=FakeDecisionLog(entries))
        score = loop._eval_task_completion(0.30)
        assert score == 0.5

    def test_task_completion_all_success(self):
        entries = [
            {"decision_type": "task_outcome", "actual_outcome": "success"},
            {"decision_type": "task_outcome", "actual_outcome": "success"},
        ]
        loop = ImprovementLoop(decision_log=FakeDecisionLog(entries))
        score = loop._eval_task_completion(0.30)
        assert score == 0.0

    def test_goal_achievement_returns_zero_without_goal_system(self):
        loop = ImprovementLoop()
        score = loop._eval_goal_achievement(0.30)
        assert score == 0.0

    def test_goal_achievement_with_abandoned_goals(self):
        gs = GoalSystem()
        gs.create_goal("test goal 1", "criteria")
        gs.create_goal("test goal 2", "criteria")
        gs.create_goal("test goal 3", "criteria")
        gs.list_all()[0].abandon("no longer relevant")
        gs.list_all()[1].block("dependency missing")
        loop = ImprovementLoop(goal_system=gs)
        score = loop._eval_goal_achievement(0.30)
        assert score > 0.5

    def test_trigger_config_includes_new_dimensions(self):
        loop = ImprovementLoop()
        assert "task_completion" in loop.trigger_config
        assert "goal_achievement" in loop.trigger_config
        assert loop.trigger_config["task_completion"]["weight"] == 0.15
        assert loop.trigger_config["goal_achievement"]["weight"] == 0.10
