"""Tests for the goal system."""

import pytest
from tain_agent.evolution.goal import Goal, GoalSystem


class TestGoal:
    def test_create_goal(self):
        g = Goal(description="Learn about the world", success_criteria="Can explain basics")
        assert g.description == "Learn about the world"
        assert g.status == "pending"

    def test_goal_lifecycle(self):
        g = Goal(description="Write a poem", success_criteria="A poem exists")
        assert g.status == "pending"
        # complete() transitions directly
        g.complete()
        assert g.status == "completed"

    def test_goal_abandon(self):
        g = Goal(description="Impossible task", success_criteria="Never")
        g.abandon("Too hard")
        assert g.status == "abandoned"

    def test_goal_block(self):
        g = Goal(description="Depends on other", success_criteria="Dependency done")
        g.block("Waiting for dependency")
        assert g.status == "blocked"

    def test_goal_to_dict(self):
        g = Goal(description="Test", success_criteria="Test passes")
        d = g.to_dict()
        assert d["description"] == "Test"
        assert d["status"] == "pending"


class TestGoalSystem:
    def test_empty_system(self):
        gs = GoalSystem()
        assert len(gs.list_all()) == 0
        assert gs.get_current() is None

    def test_create_goal(self):
        gs = GoalSystem()
        g = gs.create_goal("First goal", "Goal is done")
        assert len(gs.list_all()) == 1
        assert gs.get_current() is not None
        assert gs.get_current().description == "First goal"

    def test_list_active(self):
        gs = GoalSystem()
        gs.create_goal("Active 1", "Done")
        gs.create_goal("Active 2", "Done")
        # First goal was replaced as current, both are pending
        active = gs.list_active()
        assert len(active) == 2

    def test_list_all(self):
        gs = GoalSystem()
        gs.create_goal("A", "Done A")
        gs.create_goal("B", "Done B")
        assert len(gs.list_all()) == 2

    def test_complete_current(self):
        gs = GoalSystem()
        gs.create_goal("First", "Done")
        completed = gs.complete_current()
        assert completed.status == "completed"

    def test_abandon_current(self):
        gs = GoalSystem()
        gs.create_goal("To abandon", "Never")
        abandoned = gs.abandon_current("Not worth it")
        assert abandoned.status == "abandoned"
        assert gs.get_current() is None

    def test_switch_to(self):
        gs = GoalSystem()
        g1 = gs.create_goal("Goal 1", "Done 1")
        g2 = gs.create_goal("Goal 2", "Done 2")
        assert gs.switch_to(g1.id) is True
        assert gs.get_current().id == g1.id

    def test_summary(self):
        gs = GoalSystem()
        summary = gs.summary()
        assert "No goals" in summary
        gs.create_goal("Test goal", "Success criteria")
        summary = gs.summary()
        assert "Test goal" in summary
