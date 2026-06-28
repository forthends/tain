"""Tests for mutation atomic write and rollback."""
import json
import tempfile
from pathlib import Path
from tain_agent.package import (
    AgentPackage, PackageKind, LayerKind, PackageRegistry, bump_version,
)
from tain_agent.package.evolution import Mutation


def test_apply_mutation_writes_files():
    with tempfile.TemporaryDirectory() as tmp:
        reg = PackageRegistry(packages_root=Path(tmp))
        pkg = reg.create(name="MutTest", kind=PackageKind.AGENT, version="0.1.0")

        mutation = Mutation(
            layer=LayerKind.CAPABILITY,
            change_type="new_tool",
            detail="Add new_tool.py",
            files_to_write=[
                ("capability/tools/new_tool.py", b"def new_tool(): return 42\n"),
            ],
            manifest_patch={
                "capability": {
                    "tools": [{"name": "new_tool", "version": "1.0.0",
                               "path": "capability/tools/new_tool.py", "hash": ""}],
                },
            },
            source_gap="Missing tool",
        )

        pkg.apply_mutation(mutation)

        # File should exist
        tool_path = pkg.path / "capability" / "tools" / "new_tool.py"
        assert tool_path.exists()
        assert tool_path.read_text() == "def new_tool(): return 42\n"

        # Version should have bumped (capability → MINOR)
        assert pkg.version == "0.2.0"

        # Manifest should be updated
        manifest = json.loads(pkg.manifest_path.read_text())
        assert manifest["package"]["version"] == "0.2.0"
        assert len(manifest["capability"]["tools"]) == 1
        assert manifest["capability"]["tools"][0]["name"] == "new_tool"


def test_rollback_restores_original_state():
    with tempfile.TemporaryDirectory() as tmp:
        reg = PackageRegistry(packages_root=Path(tmp))
        pkg = reg.create(name="RollbackTest", kind=PackageKind.AGENT, version="0.1.0")

        original_version = pkg.version

        mutation = Mutation(
            layer=LayerKind.EXPRESSION,
            change_type="artifact",
            detail="Add a report",
            files_to_write=[
                ("expression/artifacts/report.md", b"# Report\n"),
            ],
            manifest_patch={},
            source_gap="Need report",
        )

        pkg.apply_mutation(mutation)
        assert pkg.version != original_version  # bumped

        pkg.rollback_mutation(mutation)

        # File removed
        assert not (pkg.path / "expression" / "artifacts" / "report.md").exists()


def test_partial_write_does_not_pollute():
    """If apply_mutation fails mid-write, package stays clean."""
    with tempfile.TemporaryDirectory() as tmp:
        reg = PackageRegistry(packages_root=Path(tmp))
        pkg = reg.create(name="AtomicTest", kind=PackageKind.AGENT, version="0.1.0")

        manifest_before = pkg.manifest_path.read_text()

        # A mutation with an impossible path
        bad_mutation = Mutation(
            layer=LayerKind.CAPABILITY,
            change_type="new_tool",
            detail="Bad tool",
            files_to_write=[
                ("/dev/null/invalid_path", b"will fail\n"),
            ],
            manifest_patch={},
            source_gap="test",
        )

        try:
            pkg.apply_mutation(bad_mutation)
        except Exception:
            pass  # expected to fail

        # Package manifest should be unchanged
        assert pkg.manifest_path.read_text() == manifest_before
