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


def test_evolve_full_cycle():
    """End-to-end: package.evolve() with mock callables."""
    with tempfile.TemporaryDirectory() as tmp:
        reg = PackageRegistry(packages_root=Path(tmp))
        pkg = reg.create(name="EvolveTest", kind=PackageKind.AGENT, version="0.1.0")

        def gap_detector(pkg):
            return {"type": "missing_tool", "detail": "Need a test tool"}

        def mutation_generator(gap, pkg):
            return Mutation(
                layer=LayerKind.CAPABILITY,
                change_type="new_tool",
                detail="Add test tool from gap",
                files_to_write=[
                    ("capability/tools/evolved_tool.py",
                     b"def evolved(): return 'ok'\n"),
                ],
                manifest_patch={
                    "capability": {
                        "tools": [{"name": "evolved_tool", "version": "1.0.0",
                                   "path": "capability/tools/evolved_tool.py",
                                   "hash": ""}],
                    },
                },
                source_gap="Need a test tool",
            )

        def contract_checker(mutation, pkg):
            return True, []

        def online_verifier(mutation, pkg):
            return True, []

        result = pkg.evolve(gap_detector, mutation_generator,
                            contract_checker, online_verifier)

        assert result.success is True
        assert result.version_from == "0.1.0"
        assert result.version_to == "0.2.0"  # capability → MINOR bump
        assert (pkg.path / "capability" / "tools" / "evolved_tool.py").exists()


def test_evolve_no_gap_returns_early():
    with tempfile.TemporaryDirectory() as tmp:
        reg = PackageRegistry(packages_root=Path(tmp))
        pkg = reg.create(name="NoGapTest", kind=PackageKind.AGENT, version="0.1.0")

        def gap_detector(pkg):
            return None  # no gap

        result = pkg.evolve(gap_detector, None, None, None)
        assert result.success is False
        assert result.stage_failed == "detect_gap"


def test_evolve_contract_check_fails():
    with tempfile.TemporaryDirectory() as tmp:
        reg = PackageRegistry(packages_root=Path(tmp))
        pkg = reg.create(name="ContractFail", kind=PackageKind.AGENT, version="0.1.0")

        m = Mutation(LayerKind.CAPABILITY, "new_tool", "bad", [], {}, "gap")

        def gap_detector(pkg):
            return {"type": "gap"}

        def mutation_generator(gap, pkg):
            return m

        def contract_checker(mutation, pkg):
            return False, ["AST safety scan failed"]

        result = pkg.evolve(gap_detector, mutation_generator,
                            contract_checker, lambda m, pk: (True, []))
        assert result.success is False
        assert result.stage_failed == "contract_check"
        assert "AST safety scan failed" in result.errors


def test_evolve_online_verify_fails_rollback():
    with tempfile.TemporaryDirectory() as tmp:
        reg = PackageRegistry(packages_root=Path(tmp))
        pkg = reg.create(name="VerifyFail", kind=PackageKind.AGENT, version="0.1.0")

        m = Mutation(
            LayerKind.EXPRESSION,
            "artifact", "Add report",
            [("expression/artifacts/bad_report.md", b"# Bad\n")],
            {}, "gap",
        )

        def gap_detector(pkg):
            return {"type": "gap"}

        def mutation_generator(gap, pkg):
            return m

        def contract_checker(mutation, pkg):
            return True, []

        def online_verifier(mutation, pkg):
            return False, ["Report incomplete"]

        result = pkg.evolve(gap_detector, mutation_generator,
                            contract_checker, online_verifier)
        assert result.success is False
        assert result.stage_failed == "online_verify"
        # File should have been rolled back
        assert not (pkg.path / "expression" / "artifacts" / "bad_report.md").exists()
