"""Tests for tain_agent.core.config"""

import tempfile
from pathlib import Path
from unittest.mock import patch

import yaml
import pytest
from tain_agent.core.config import (
    load_config,
    load_agent_overrides,
    deep_merge,
    get_config_files,
    DEFAULT_CONFIG,
)


class TestDeepMerge:
    def test_simple_merge(self):
        base = {"a": 1, "b": 2}
        override = {"b": 3, "c": 4}
        deep_merge(base, override)
        assert base == {"a": 1, "b": 3, "c": 4}

    def test_nested_merge(self):
        base = {"a": {"x": 1, "y": 2}, "b": 3}
        override = {"a": {"y": 99, "z": 100}}
        deep_merge(base, override)
        assert base == {"a": {"x": 1, "y": 99, "z": 100}, "b": 3}

    def test_override_replaces_list(self):
        base = {"items": [1, 2, 3]}
        override = {"items": [4, 5]}
        deep_merge(base, override)
        assert base["items"] == [4, 5]

    def test_empty_override(self):
        base = {"a": 1}
        override = {}
        deep_merge(base, override)
        assert base == {"a": 1}

    def test_new_key_added(self):
        base = {"a": 1}
        override = {"b": {"c": 3}}
        deep_merge(base, override)
        assert base == {"a": 1, "b": {"c": 3}}


class TestLoadConfig:
    def test_defaults_only(self):
        with patch("tain_agent.core.config.Path.cwd") as mock_cwd, \
             patch("tain_agent.core.config.Path.home") as mock_home:
            with tempfile.TemporaryDirectory() as d:
                mock_cwd.return_value = Path(d)
                mock_home.return_value = Path(d)
                config = load_config()
                assert config["framework"]["version"] == "0.4.3"
                assert config["llm"]["retry"]["max_retries"] == 3

    def test_project_config_overrides_defaults(self):
        with tempfile.TemporaryDirectory() as d:
            tmp = Path(d)
            project_cfg = tmp / "config.yaml"
            project_cfg.write_text(yaml.dump({
                "llm": {"model": "custom-model"},
                "agent": {"timezone": "UTC"},
            }))
            with patch("tain_agent.core.config.Path.cwd", return_value=tmp), \
                 patch("tain_agent.core.config.Path.home", return_value=tmp):
                config = load_config()
                assert config["llm"]["model"] == "custom-model"
                assert config["agent"]["timezone"] == "UTC"
                # Defaults should still be present for non-overridden keys
                assert config["llm"]["retry"]["max_retries"] == 3

    def test_user_config_loaded(self):
        with tempfile.TemporaryDirectory() as d:
            tmp = Path(d)
            home_tain = tmp / ".tain"
            home_tain.mkdir()
            user_cfg = home_tain / "config.yaml"
            user_cfg.write_text(yaml.dump({
                "llm": {"retry": {"max_retries": 5}},
            }))
            with patch("tain_agent.core.config.Path.cwd", return_value=tmp), \
                 patch("tain_agent.core.config.Path.home", return_value=tmp):
                config = load_config()
                assert config["llm"]["retry"]["max_retries"] == 5

    def test_explicit_config_highest_priority(self):
        with tempfile.TemporaryDirectory() as d:
            tmp = Path(d)
            project_cfg = tmp / "config.yaml"
            project_cfg.write_text(yaml.dump({"llm": {"model": "project-model"}}))
            explicit_cfg = tmp / "explicit.yaml"
            explicit_cfg.write_text(yaml.dump({"llm": {"model": "explicit-model"}}))
            with patch("tain_agent.core.config.Path.cwd", return_value=tmp), \
                 patch("tain_agent.core.config.Path.home", return_value=tmp):
                config = load_config(explicit_path=str(explicit_cfg))
                assert config["llm"]["model"] == "explicit-model"

    def test_missing_explicit_path_falls_through(self):
        with tempfile.TemporaryDirectory() as d:
            tmp = Path(d)
            project_cfg = tmp / "config.yaml"
            project_cfg.write_text(yaml.dump({"llm": {"model": "project-model"}}))
            with patch("tain_agent.core.config.Path.cwd", return_value=tmp), \
                 patch("tain_agent.core.config.Path.home", return_value=tmp):
                config = load_config(explicit_path="/nonexistent/path.yaml")
                assert config["llm"]["model"] == "project-model"

    def test_corrupt_yaml_doesnt_crash(self):
        with tempfile.TemporaryDirectory() as d:
            tmp = Path(d)
            (tmp / "config.yaml").write_text("{invalid yaml!!!")
            with patch("tain_agent.core.config.Path.cwd", return_value=tmp), \
                 patch("tain_agent.core.config.Path.home", return_value=tmp):
                config = load_config()
                # Should return defaults without crashing
                assert config["framework"]["version"] == "0.4.3"


class TestLoadAgentOverrides:
    def test_no_override_file(self):
        with tempfile.TemporaryDirectory() as d:
            base = {"llm": {"model": "base"}}
            result = load_agent_overrides(base, "test_agent", workspace_dir=d)
            assert result["llm"]["model"] == "base"

    def test_agent_override_applied(self):
        with tempfile.TemporaryDirectory() as d:
            ws = Path(d) / "test_agent"
            ws.mkdir(parents=True)
            agent_yaml = ws / "agent.yaml"
            agent_yaml.write_text(yaml.dump({
                "llm": {"model": "agent-specific-model"},
                "agent": {"timezone": "America/New_York"},
            }))
            base = {
                "llm": {"model": "base", "max_tokens": 8192},
                "agent": {"timezone": "UTC"},
            }
            result = load_agent_overrides(base, "test_agent", workspace_dir=d)
            assert result["llm"]["model"] == "agent-specific-model"
            assert result["llm"]["max_tokens"] == 8192  # Preserved from base
            assert result["agent"]["timezone"] == "America/New_York"

    def test_agent_override_does_not_mutate_original(self):
        with tempfile.TemporaryDirectory() as d:
            ws = Path(d) / "test_agent"
            ws.mkdir(parents=True)
            (ws / "agent.yaml").write_text(yaml.dump({"llm": {"model": "override"}}))
            base = {"llm": {"model": "base"}}
            result = load_agent_overrides(base, "test_agent", workspace_dir=d)
            assert base["llm"]["model"] == "base"
            assert result["llm"]["model"] == "override"

    def test_corrupt_agent_yaml(self):
        with tempfile.TemporaryDirectory() as d:
            ws = Path(d) / "test_agent"
            ws.mkdir(parents=True)
            (ws / "agent.yaml").write_text("{corrupt!!!")
            base = {"llm": {"model": "base"}}
            result = load_agent_overrides(base, "test_agent", workspace_dir=d)
            assert result == base


class TestGetConfigFiles:
    def test_returns_list(self):
        files = get_config_files()
        assert len(files) == 4
        assert files[0]["priority"] == 1  # Sorted by priority ascending
        assert files[-1]["priority"] == 4
