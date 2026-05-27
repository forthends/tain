"""Tests for tain_agent.tools.primal memory tools"""

import json
import tempfile
from pathlib import Path
from unittest.mock import patch
from tain_agent.tools.primal import remember_note, recall_notes, _get_notes_path


class TestRememberNote:
    def test_saves_note(self):
        with tempfile.TemporaryDirectory() as d:
            ws = Path(d)
            with patch("tain_agent.tools.primal._WORKSPACE_DIR", ws):
                result = remember_note(category="discovery", content="Found something interesting")
                assert result["status"] == "saved"
                assert result["note"]["category"] == "discovery"
                assert result["note"]["content"] == "Found something interesting"
                assert "timestamp" in result["note"]

    def test_note_persisted(self):
        with tempfile.TemporaryDirectory() as d:
            ws = Path(d)
            (ws / "memory").mkdir()
            with patch("tain_agent.tools.primal._WORKSPACE_DIR", ws):
                remember_note(category="pattern", content="Recurring theme")
                notes_path = ws / "memory" / "agent_notes.jsonl"
                assert notes_path.exists()
                data = json.loads(notes_path.read_text().strip())
                assert data["category"] == "pattern"

    def test_category_normalized(self):
        with tempfile.TemporaryDirectory() as d:
            ws = Path(d)
            with patch("tain_agent.tools.primal._WORKSPACE_DIR", ws):
                result = remember_note(category="  User_Preference  ", content="Likes concise")
                assert result["note"]["category"] == "user_preference"


class TestRecallNotes:
    def test_empty_without_notes(self):
        with tempfile.TemporaryDirectory() as d:
            ws = Path(d)
            with patch("tain_agent.tools.primal._WORKSPACE_DIR", ws):
                result = recall_notes()
                assert result["total"] == 0
                assert result["notes"] == []

    def test_recall_all(self):
        with tempfile.TemporaryDirectory() as d:
            ws = Path(d)
            with patch("tain_agent.tools.primal._WORKSPACE_DIR", ws):
                remember_note("discovery", "First discovery")
                remember_note("pattern", "A pattern")
                remember_note("discovery", "Second discovery")
                result = recall_notes()
                assert result["total"] == 3
                assert len(result["notes"]) == 3

    def test_recall_filtered_by_category(self):
        with tempfile.TemporaryDirectory() as d:
            ws = Path(d)
            with patch("tain_agent.tools.primal._WORKSPACE_DIR", ws):
                remember_note("discovery", "Alpha")
                remember_note("pattern", "Beta")
                remember_note("discovery", "Gamma")
                result = recall_notes(category="discovery")
                assert result["total"] == 2
                for note in result["notes"]:
                    assert note["category"] == "discovery"

    def test_recall_with_limit(self):
        with tempfile.TemporaryDirectory() as d:
            ws = Path(d)
            with patch("tain_agent.tools.primal._WORKSPACE_DIR", ws):
                for i in range(10):
                    remember_note("test", f"Note {i}")
                result = recall_notes(limit=3)
                assert result["total"] == 10
                assert len(result["notes"]) == 3
                assert result["shown"] == 3

    def test_recall_newest_first(self):
        with tempfile.TemporaryDirectory() as d:
            ws = Path(d)
            with patch("tain_agent.tools.primal._WORKSPACE_DIR", ws):
                remember_note("test", "Oldest")
                import time
                time.sleep(0.01)
                remember_note("test", "Newest")
                result = recall_notes()
                # Newest should be first
                assert result["notes"][0]["content"] == "Newest"


class TestGetNotesPath:
    def test_with_workspace(self):
        with tempfile.TemporaryDirectory() as d:
            ws = Path(d)
            with patch("tain_agent.tools.primal._WORKSPACE_DIR", ws):
                path = _get_notes_path()
                assert path.parent == ws / "memory"
                assert path.name == "agent_notes.jsonl"

    def test_without_workspace(self):
        with patch("tain_agent.tools.primal._WORKSPACE_DIR", None):
            path = _get_notes_path()
            assert path.name == "agent_notes.jsonl"
