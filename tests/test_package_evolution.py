"""Tests for package-level evolution (Mutation, EvolutionResult, AgentPackage.evolve)."""
import tempfile
from pathlib import Path
from tain_agent.package import AgentPackage, PackageKind, LayerKind, PackageRegistry
from tain_agent.package.evolution import Mutation, EvolutionResult


def test_mutation_creation():
    m = Mutation(
        layer=LayerKind.CAPABILITY,
        change_type="new_tool",
        detail="Add a test tool",
        files_to_write=[("capability/tools/test_tool.py", b"def test(): pass\n")],
        manifest_patch={"capability": {"tools": [{"name": "test_tool", "version": "1.0.0"}]}},
        source_gap="Missing test capability",
    )
    assert m.layer == LayerKind.CAPABILITY
    assert m.change_type == "new_tool"
    assert len(m.files_to_write) == 1
    assert m.detail == "Add a test tool"


def test_evolution_result_no_gap():
    result = EvolutionResult.no_gap("0.1.0")
    assert result.success is False
    assert result.stage_failed == "detect_gap"
    assert result.version_to is None


def test_evolution_result_success():
    m = Mutation(LayerKind.EXPRESSION, "artifact", "test", [], {}, "gap")
    result = EvolutionResult.success_result("0.1.0", "0.1.1", m)
    assert result.success is True
    assert result.version_from == "0.1.0"
    assert result.version_to == "0.1.1"
    assert result.mutation is m


def test_evolution_result_contract_failed():
    m = Mutation(LayerKind.CAPABILITY, "new_tool", "test", [], {}, "gap")
    result = EvolutionResult.contract_failed("0.1.0", m, ["AST scan failed"])
    assert result.success is False
    assert result.stage_failed == "contract_check"
    assert result.errors == ["AST scan failed"]


def test_evolution_result_write_failed():
    m = Mutation(LayerKind.EXPRESSION, "artifact", "test", [], {}, "gap")
    result = EvolutionResult.write_failed("0.1.0", m, ["Disk full"])
    assert result.success is False
    assert result.stage_failed == "write_package"


def test_evolution_result_rolled_back():
    m = Mutation(LayerKind.EXPRESSION, "artifact", "test", [], {}, "gap")
    result = EvolutionResult.rolled_back(m, ["Verification failed"])
    assert result.success is False
    assert result.stage_failed == "online_verify"
