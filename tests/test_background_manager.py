"""Tests for tain_agent.tools.background_manager"""

import time
import pytest
from tain_agent.tools.background_manager import (
    BackgroundShellManager, BackgroundProcess, bg_start, bg_output,
    bg_kill, bg_list, bg_wait, init_manager, get_manager,
)


class TestBackgroundShellManager:
    def test_init(self):
        mgr = BackgroundShellManager(workspace_dir="/tmp")
        assert mgr.workspace_dir == "/tmp"
        assert mgr.processes == {}

    def test_start_simple_command(self):
        mgr = BackgroundShellManager()
        try:
            result = mgr.start("echo hello")
            assert result["success"] is True
            assert result["command"] == "echo hello"
            assert "process_id" in result
            pid = result["process_id"]

            # Wait for it to finish
            wait_result = mgr.wait(pid, timeout=5)
            assert wait_result["success"] is True
        finally:
            mgr.kill_all()

    def test_start_command_with_output(self):
        mgr = BackgroundShellManager()
        try:
            result = mgr.start("bash -c 'echo line1 && sleep 0.3 && echo line2'")
            assert result["success"]
            pid = result["process_id"]

            # Wait for completion
            wait_result = mgr.wait(pid, timeout=5)
            assert wait_result["success"] is True
            output = wait_result.get("output", "")
            assert "line1" in output
        finally:
            mgr.kill_all()

    def test_get_output(self):
        mgr = BackgroundShellManager()
        try:
            result = mgr.start("bash -c 'echo output_line_1 && sleep 0.3 && echo output_line_2'")
            pid = result["process_id"]
            time.sleep(0.5)
            out = mgr.get_output(pid)
            assert out["success"] is True
            assert "output_line_1" in out["output"]
        finally:
            mgr.kill_all()

    def test_get_output_nonexistent(self):
        mgr = BackgroundShellManager()
        result = mgr.get_output("nonexistent_id")
        assert result["success"] is False

    def test_kill_process(self):
        mgr = BackgroundShellManager()
        try:
            result = mgr.start("sleep 30")
            assert result["success"]
            pid = result["process_id"]
            kill_result = mgr.kill(pid)
            assert kill_result["success"] is True
            assert pid not in mgr.processes
        finally:
            mgr.kill_all()

    def test_kill_nonexistent(self):
        mgr = BackgroundShellManager()
        result = mgr.kill("nonexistent")
        assert result["success"] is False

    def test_list_processes(self):
        mgr = BackgroundShellManager()
        try:
            mgr.start("sleep 10")
            mgr.start("sleep 10")
            result = mgr.list_processes()
            assert result["success"] is True
            assert result["total"] == 2
            assert len(result["processes"]) == 2
            for p in result["processes"]:
                assert "id" in p
                assert "command" in p
                assert "running" in p
        finally:
            mgr.kill_all()

    def test_max_processes_limit(self):
        mgr = BackgroundShellManager()
        try:
            for i in range(BackgroundShellManager.MAX_PROCESSES):
                result = mgr.start(f"sleep 5")
                assert result["success"] is True

            # Should fail at limit
            result = mgr.start("sleep 1")
            assert result["success"] is False
            assert "limit" in result.get("error", "").lower()
        finally:
            mgr.kill_all()

    def test_wait_with_timeout(self):
        mgr = BackgroundShellManager()
        try:
            result = mgr.start("sleep 30")
            pid = result["process_id"]
            wait_result = mgr.wait(pid, timeout=1)
            assert wait_result["success"] is True
            assert wait_result.get("timed_out") is True
        finally:
            mgr.kill_all()

    def test_wait_nonexistent(self):
        mgr = BackgroundShellManager()
        result = mgr.wait("nonexistent", timeout=1)
        assert result["success"] is False

    def test_kill_all(self):
        mgr = BackgroundShellManager()
        mgr.start("sleep 10")
        mgr.start("sleep 10")
        count = mgr.kill_all()
        assert count == 2
        assert mgr.processes == {}


class TestBackgroundProcess:
    def test_dataclass_defaults(self):
        bp = BackgroundProcess(
            id="test_1",
            command="echo hello",
            process=None,
            started_at="2026-01-01T00:00:00",
        )
        assert bp.id == "test_1"
        assert bp.command == "echo hello"
        assert bp.output_buffer == []
        assert bp._max_buffer == 2000


class TestModuleLevelSingleton:
    def test_init_manager(self):
        mgr = init_manager("/tmp/test_ws")
        assert mgr.workspace_dir == "/tmp/test_ws"
        assert get_manager() is mgr

    def test_bg_start_uses_manager(self):
        init_manager("")
        try:
            result = bg_start("echo singleton_test")
            assert result["success"] is True
            pid = result["process_id"]
            bg_kill(pid)
        finally:
            get_manager().kill_all()
