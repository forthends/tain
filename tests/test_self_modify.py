"""Tests for the SelfModify safety mechanisms."""

import pytest
import time
import tempfile
from pathlib import Path
from tain_agent.evolution.self_modify import SelfModify


class TestSelfModifyProtectedPaths:
    def test_protected_path_matched(self):
        sm = SelfModify(
            base_dir="/tmp/test_agent",
            protected_paths=["tain_agent/core/agent.py", "config.yaml"],
        )
        assert sm._is_protected("tain_agent/core/agent.py") is True

    def test_unprotected_path_allowed(self):
        sm = SelfModify(
            base_dir="/tmp/test_agent",
            protected_paths=["tain_agent/core/agent.py"],
        )
        assert sm._is_protected("agent_workspace/test/files/data.txt") is False

    def test_parent_dir_traversal_blocked(self):
        sm = SelfModify(
            base_dir="/tmp/test_agent",
            protected_paths=[],
        )
        assert sm._is_protected("../outside/file.txt") is True

    def test_component_level_matching(self):
        sm = SelfModify(
            base_dir="/tmp/test_agent",
            protected_paths=["tain_agent/core"],
        )
        assert sm._is_protected("tain_agent/core/agent.py") is True

    def test_absolute_path_outside_base_is_protected(self):
        sm = SelfModify(
            base_dir="/tmp/test_agent",
            protected_paths=[],
        )
        assert sm._is_protected("/etc/passwd") is True


class TestSelfModifyRateLimiting:
    def test_basic_rate_limit_after_max_mods(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            sm = SelfModify(base_dir=tmpdir)
            test_file = Path(tmpdir) / "mod_test.txt"
            test_file.write_text("v0")

            # Do max modifications
            for i in range(sm._MAX_MODS_PER_FILE):
                result = sm.modify_file("mod_test.txt", f"v{i}", f"v{i+1}")
                assert result["success"] is True

            # Next one should be rate limited
            result = sm.modify_file(
                "mod_test.txt",
                f"v{sm._MAX_MODS_PER_FILE}",
                f"v{sm._MAX_MODS_PER_FILE + 1}",
            )
            assert result["success"] is False

    def test_rate_limit_timestamps_cleaned(self):
        """Old timestamps outside window should be pruned."""
        with tempfile.TemporaryDirectory() as tmpdir:
            sm = SelfModify(base_dir=tmpdir)
            test_file = Path(tmpdir) / "old_test.txt"
            test_file.write_text("original")

            # Manually set old timestamps
            old_time = time.time() - sm._MOD_WINDOW_SECONDS - 60
            sm._mod_timestamps["old_test.txt"] = [old_time] * sm._MAX_MODS_PER_FILE

            # Should succeed since old timestamps are pruned
            result = sm.modify_file("old_test.txt", "original", "new")
            assert result["success"] is True


class TestSelfModifyFileOperations:
    def test_read_self(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            sm = SelfModify(base_dir=tmpdir)
            test_file = Path(tmpdir) / "test.txt"
            test_file.write_text("hello world")
            content = sm.read_self("test.txt")
            assert content == "hello world"

    def test_modify_file_not_found(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            sm = SelfModify(base_dir=tmpdir)
            result = sm.modify_file("nonexistent.txt", "old", "new")
            assert result["success"] is False

    def test_modify_protected_file_blocked(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            sm = SelfModify(
                base_dir=tmpdir,
                protected_paths=["protected.txt"],
            )
            protected = Path(tmpdir) / "protected.txt"
            protected.write_text("secret")
            result = sm.modify_file("protected.txt", "secret", "changed")
            assert result["success"] is False
