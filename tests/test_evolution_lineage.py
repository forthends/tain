"""Tests for evolution lineage tracking — LineageTracker."""

import hashlib
import tempfile
from pathlib import Path

import pytest

# LineageTracker writes to disk; we must handle when the class is unavailable
try:
    from tain_agent.evolution.lineage import LineageTracker, _hash_file
    LINEAGE_AVAILABLE = True
except ImportError:
    LINEAGE_AVAILABLE = False


@pytest.mark.skipif(not LINEAGE_AVAILABLE, reason="LineageTracker not available")
class TestLineageTracker:
    """Tests for LineageTracker — the evolutionary audit trail."""

    @pytest.fixture
    def tracker(self):
        """Create a LineageTracker pointing at a temporary directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            lt = LineageTracker(lineage_dir=tmpdir, lineage_file="test_lineage.jsonl")
            yield lt

    def test_record_forge_has_required_fields(self, tracker):
        """record_forge() should produce an entry with id and timestamp."""
        entry = tracker.record_forge(
            tool_name="test_tool",
            tool_code="def main():\n    return 42\n",
            agent_version="0.9.0",
            reasoning="Needed for testing",
        )
        assert "id" in entry
        assert "timestamp" in entry
        assert isinstance(entry["id"], int)
        assert entry["event_type"] == "forge_tool"
        assert entry["artifact"] == "test_tool"
        assert entry["artifact_type"] == "tool"
        assert entry["agent_version"] == "0.9.0"
        assert entry["reasoning"] == "Needed for testing"

    def test_sha256_is_deterministic(self):
        """The SHA-256 hash used in lineage must be deterministic:
        same input always produces the same hash."""
        content = "def hello():\n    print('world')\n"
        hash_a = hashlib.sha256(content.encode()).hexdigest()[:16]
        hash_b = hashlib.sha256(content.encode()).hexdigest()[:16]
        assert hash_a == hash_b

        # Different content must produce a different hash
        hash_c = hashlib.sha256("different".encode()).hexdigest()[:16]
        assert hash_c != hash_a

    def test_sha256_different_content_different_hash(self):
        """Different inputs must produce different truncated hashes."""
        hash_1 = hashlib.sha256(b"alpha").hexdigest()[:16]
        hash_2 = hashlib.sha256(b"beta").hexdigest()[:16]
        assert hash_1 != hash_2

    def test_empty_log_queries_return_empty_list(self, tracker):
        """A fresh tracker with no entries should return [] for queries."""
        assert tracker.count() == 0
        assert tracker.lineage_for("nonexistent") == []
        assert tracker.all_tools() == []
        assert tracker.all_files() == []

    def test_multiple_events_have_unique_ids(self, tracker):
        """Each recorded event should receive a unique incrementing id."""
        e1 = tracker.record_forge("tool_a", "code_a", "0.9.0")
        e2 = tracker.record_forge("tool_b", "code_b", "0.9.0")
        e3 = tracker.record_forge("tool_c", "code_c", "0.9.0")

        ids = [e1["id"], e2["id"], e3["id"]]
        assert len(ids) == len(set(ids)), f"IDs are not unique: {ids}"
        assert e1["id"] < e2["id"] < e3["id"], f"IDs should increment: {ids}"

    def test_record_add_module_has_correct_event_type(self, tracker):
        """record_add_module() should produce an entry with event_type='add_module'."""
        entry = tracker.record_add_module(
            module_path="tain_agent/tools/new_tool.py",
            code="def main():\n    pass\n",
            agent_version="0.9.0",
            reasoning="Add new capability module",
        )
        assert entry["event_type"] == "add_module"
        assert entry["artifact"] == "tain_agent/tools/new_tool.py"
        assert entry["parent"] == "none"  # New modules have no parent

    def test_record_modify_sets_parent_and_child_hashes(self, tracker):
        """record_modify() should compute and store old and new content hashes."""
        old_code = "def old():\n    return 1\n"
        new_code = "def old():\n    return 2\n"
        entry = tracker.record_modify(
            filepath="test_file.py",
            old_content=old_code,
            new_content=new_code,
            agent_version="0.9.0",
            reasoning="Bug fix",
        )
        assert entry["event_type"] == "self_modify"
        assert entry["parent"] != entry["child"]  # different hashes
        # parent hash should match the hash of old_code
        expected_old = hashlib.sha256(old_code.encode()).hexdigest()[:16]
        assert entry["parent"] == expected_old

    def test_lineage_for_filters_by_artifact(self, tracker):
        """lineage_for(artifact) should return only entries matching that artifact."""
        tracker.record_forge("tool_x", "code_x", "0.9.0")
        tracker.record_forge("tool_y", "code_y", "0.9.0")
        tracker.record_add_module("mod_z.py", "code_z", "0.9.0")

        x_entries = tracker.lineage_for("tool_x")
        assert len(x_entries) == 1
        assert x_entries[0]["artifact"] == "tool_x"

        y_entries = tracker.lineage_for("tool_y")
        assert len(y_entries) == 1
        assert y_entries[0]["artifact"] == "tool_y"

    def test_count_reflects_all_entries(self, tracker):
        """count() should return the total number of lineage entries."""
        assert tracker.count() == 0
        tracker.record_forge("t1", "c1", "0.9.0")
        assert tracker.count() == 1
        tracker.record_forge("t2", "c2", "0.9.0")
        tracker.record_add_module("m1", "c3", "0.9.0")
        assert tracker.count() == 3

    def test_summary_includes_counts_and_lists(self, tracker):
        """summary() should return a dict with total_events, forge_events, etc."""
        tracker.record_forge("t_a", "code", "0.9.0")
        tracker.record_forge("t_b", "code", "0.9.0")
        tracker.record_add_module("mod.py", "code", "0.9.0")

        s = tracker.summary()
        assert s["total_events"] == 3
        assert s["forge_events"] == 2
        assert s["add_module_events"] == 1
        assert s["modify_events"] == 0
        assert "t_a" in s["tools_created"]
        assert "t_b" in s["tools_created"]
        assert "mod.py" in s["files_modified"]

    def test_all_tools_returns_unique_sorted_names(self, tracker):
        """all_tools() should return a deduplicated, sorted list of tool names."""
        tracker.record_forge("zebra", "c1", "0.9.0")
        tracker.record_forge("apple", "c2", "0.9.0")
        tracker.record_forge("zebra", "c3", "0.9.0")  # duplicate tool name
        tools = tracker.all_tools()
        assert tools == ["apple", "zebra"]  # sorted, deduplicated

    def test_all_files_does_not_include_forged_tools(self, tracker):
        """all_files() should NOT include forge_tool artifacts."""
        tracker.record_forge("tool_only", "code", "0.9.0")
        tracker.record_add_module("module_file.py", "code", "0.9.0")
        files = tracker.all_files()
        assert "tool_only" not in files
        assert "module_file.py" in files


class TestHashFile:
    """Tests for the _hash_file utility function."""

    def test_nonexistent_file_returns_none(self):
        """_hash_file should return 'none' for a file that does not exist."""
        result = _hash_file(Path("/tmp/nonexistent_file_xyz_12345.txt"))
        assert result == "none"

    def test_existing_file_returns_hex_hash(self):
        """_hash_file should return a 16-char hex hash for an existing file."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write("hello world\n")
            tmp_path = Path(f.name)

        try:
            result = _hash_file(tmp_path)
            assert len(result) == 16
            assert all(c in "0123456789abcdef" for c in result)
        finally:
            tmp_path.unlink()

    def test_same_content_same_hash(self):
        """Two files with identical content should produce the same hash."""
        content = "identical content for hashing\n"
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write(content)
            path_a = Path(f.name)
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write(content)
            path_b = Path(f.name)

        try:
            assert _hash_file(path_a) == _hash_file(path_b)
        finally:
            path_a.unlink()
            path_b.unlink()
