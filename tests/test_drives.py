"""Tests for the intrinsic drive system."""

import pytest
from tain_agent.core.drives import DriveSystem, DRIVE_DEFINITIONS


class TestDriveInitialization:
    def test_default_initialization(self):
        ds = DriveSystem()
        assert len(ds.drives) == 4
        for name in ("curiosity", "mastery", "creation", "conservation"):
            assert name in ds.drives
            assert 0.0 <= ds.drives[name] <= 1.0

    def test_custom_initialization(self):
        ds = DriveSystem(drives_config={
            "curiosity": 0.9,
            "mastery": 0.1,
            "creation": 0.5,
            "conservation": 0.3,
        })
        assert ds.drives["curiosity"] == 0.9
        assert ds.drives["mastery"] == 0.1

    def test_random_initialization_varies(self):
        """Drive values should vary between instances due to random init."""
        profiles = []
        for _ in range(50):
            ds = DriveSystem()
            profiles.append(tuple(ds.drives.values()))

        # At least some variation across instances
        unique = len(set(profiles))
        assert unique >= 3, f"Only {unique} unique profiles out of 50 — insufficient variation"

    def test_values_clamped(self):
        ds = DriveSystem(drives_config={
            "curiosity": 5.0,  # above 1.0
            "mastery": -1.0,   # below 0.0
        })
        assert 0.0 <= ds.drives["curiosity"] <= 1.0
        assert 0.0 <= ds.drives["mastery"] <= 1.0


class TestDriveActionFeedback:
    def test_record_action_satisfies_matching_drive(self):
        ds = DriveSystem(drives_config={
            "curiosity": 0.8, "mastery": 0.5, "creation": 0.5, "conservation": 0.5,
        })
        # web_search satisfies curiosity
        old_curiosity = ds.drives["curiosity"]
        ds.record_action("web_search")
        assert ds.drives["curiosity"] < old_curiosity  # satisfied → decreases

    def test_record_action_neglects_other_drives(self):
        ds = DriveSystem(drives_config={
            "curiosity": 0.5, "mastery": 0.5, "creation": 0.5, "conservation": 0.5,
        })
        old_mastery = ds.drives["mastery"]
        ds.record_action("web_search")  # satisfies curiosity, not mastery
        # Mastery should increase slightly (neglected)
        assert ds.drives["mastery"] >= old_mastery

    def test_record_idle_increases_all_drives(self):
        ds = DriveSystem(drives_config={
            "curiosity": 0.5, "mastery": 0.5, "creation": 0.5, "conservation": 0.5,
        })
        old_values = dict(ds.drives)
        ds.record_idle_cycle()
        for name in ds.drives:
            assert ds.drives[name] >= old_values[name]

    def test_idle_cycles_accumulate(self):
        ds = DriveSystem()
        assert ds._idle_cycles == 0
        ds.record_idle_cycle()
        ds.record_idle_cycle()
        assert ds._idle_cycles == 2
        ds.record_action("web_search")
        assert ds._idle_cycles == 0  # reset on action


class TestDriveProfile:
    def test_get_profile_returns_dominant_drive(self):
        ds = DriveSystem(drives_config={
            "curiosity": 0.9, "mastery": 0.3, "creation": 0.4, "conservation": 0.2,
        })
        profile = ds.get_profile()
        assert profile["dominant_drive"] == "curiosity"
        assert "personality_hint" in profile
        assert "exploration" in profile

    def test_balanced_profile(self):
        ds = DriveSystem(drives_config={
            "curiosity": 0.5, "mastery": 0.5, "creation": 0.5, "conservation": 0.5,
        })
        hint = ds._derive_personality_hint()
        assert "平衡者" in hint or "均衡" in hint


class TestExplorationScore:
    def test_exploration_score_is_bounded(self):
        ds = DriveSystem()
        score = ds.compute_exploration_score()
        assert 0.0 <= score <= 1.0

    def test_grows_with_idle_cycles(self):
        ds = DriveSystem(drives_config={"curiosity": 0.8})
        for _ in range(10):
            ds.record_idle_cycle()
        score = ds.compute_exploration_score()
        assert score > 0.0

    def test_exploration_score_capped_at_one(self):
        ds = DriveSystem(drives_config={"curiosity": 1.0})
        ds._idle_cycles = 1000
        assert ds.compute_exploration_score() <= 1.0


class TestDriveSuggestions:
    def test_suggest_action_type_returns_string(self):
        ds = DriveSystem()
        suggestion = ds.suggest_action_type()
        assert isinstance(suggestion, str)
        assert len(suggestion) > 0

    def test_dominate_drive_returns_drive_name(self):
        ds = DriveSystem()
        dominant = ds.dominate_drive()
        assert dominant in DRIVE_DEFINITIONS
