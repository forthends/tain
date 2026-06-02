"""Tests for SkillPlugin — skill model, composer, and plugin integration."""

import tempfile
from pathlib import Path

from tain_agent.kernel.protocol import AgentContext, PluginProtocol
from tain_agent.plugins.skill import SkillPlugin
from tain_agent.plugins.skill.composer import compose_skills
from tain_agent.plugins.skill.model import (
    MaturityLevel,
    MATURITY_THRESHOLDS,
    Skill,
    Step,
)


class TestSkill:
    """Tests for the Skill dataclass and maturity tracking."""

    def test_record_use_updates_stats(self):
        skill = Skill(name="test", display_name="Test Skill")
        assert skill.usage_count == 0
        assert skill.success_count == 0

        skill.record_use(success=True)
        assert skill.usage_count == 1
        assert skill.success_count == 1
        assert skill.success_rate == 1.0

    def test_maturity_advances_with_success(self):
        skill = Skill(name="test", display_name="Test Skill")
        assert skill.maturity == MaturityLevel.NOVICE

        # Reach APPRENTICE (5 successes)
        for _ in range(5):
            skill.record_use(success=True)
        assert skill.maturity == MaturityLevel.APPRENTICE

    def test_failed_uses_delay_maturity(self):
        skill = Skill(name="test", display_name="Test Skill")

        # Mix of successes and failures
        for _ in range(3):
            skill.record_use(success=True)
        for _ in range(5):
            skill.record_use(success=False)

        # 3 successes out of 8 = 37.5% < 50%, effective = 1 (halved)
        assert skill.usage_count == 8
        assert skill.success_count == 3
        assert skill.maturity == MaturityLevel.NOVICE

    def test_success_rate_zero_when_no_uses(self):
        skill = Skill(name="test", display_name="Test Skill")
        assert skill.success_rate == 0.0

    def test_to_dict_and_from_dict_roundtrip(self):
        skill = Skill(
            name="coding",
            display_name="Code Generation",
            description="Generate code from specs",
            category="engineering",
            tools=["forge", "test"],
            knowledge_refs=["python", "design_patterns"],
            workflow=[Step(name="analyze", description="Analyze requirements")],
            maturity=MaturityLevel.COMPETENT,
            usage_count=25,
            success_count=22,
        )
        d = skill.to_dict()
        restored = Skill.from_dict(d)
        assert restored.name == "coding"
        assert restored.display_name == "Code Generation"
        assert restored.maturity == MaturityLevel.COMPETENT
        assert restored.tools == ["forge", "test"]
        assert len(restored.workflow) == 1
        assert restored.workflow[0].name == "analyze"

    def test_maturity_thresholds_monotonic(self):
        levels = list(MaturityLevel)
        prev = -1
        for lv in levels:
            assert MATURITY_THRESHOLDS[lv] >= prev
            prev = MATURITY_THRESHOLDS[lv]


class TestComposer:
    """Tests for skill composition."""

    def test_compose_inherits_tools(self):
        s1 = Skill(name="a", display_name="A", tools=["t1", "t2"])
        s2 = Skill(name="b", display_name="B", tools=["t2", "t3"])

        composed = compose_skills("c", "C", "Composed", [s1, s2])
        assert "t1" in composed.tools
        assert "t2" in composed.tools
        assert "t3" in composed.tools
        # Deduplication
        assert composed.tools.count("t2") == 1

    def test_compose_initial_maturity_is_min_minus_one(self):
        s1 = Skill(name="a", display_name="A", maturity=MaturityLevel.COMPETENT)
        s2 = Skill(name="b", display_name="B", maturity=MaturityLevel.PROFICIENT)

        composed = compose_skills("c", "C", "Composed", [s1, s2])
        # min(COMPETENT=3, PROFICIENT=4) → 3-1 = 2 = APPRENTICE
        assert composed.maturity == MaturityLevel.APPRENTICE

    def test_compose_with_custom_workflow(self):
        s1 = Skill(name="a", display_name="A")
        s2 = Skill(name="b", display_name="B")
        wf = [Step(name="custom_step", description="A custom step")]

        composed = compose_skills("c", "C", "Composed", [s1, s2], workflow=wf)
        assert len(composed.workflow) == 1
        assert composed.workflow[0].name == "custom_step"

    def test_compose_merges_knowledge_refs(self):
        s1 = Skill(name="a", display_name="A", knowledge_refs=["k1"])
        s2 = Skill(name="b", display_name="B", knowledge_refs=["k2", "k1"])

        composed = compose_skills("c", "C", "Composed", [s1, s2])
        assert sorted(composed.knowledge_refs) == ["k1", "k2"]

    def test_compose_empty_skills_novice(self):
        composed = compose_skills("c", "C", "Composed", [])
        assert composed.maturity == MaturityLevel.NOVICE


class TestSkillPlugin:
    """Tests for the SkillPlugin itself."""

    def _make_ctx(self, tmpdir):
        return AgentContext(
            agent_name="test",
            agent_id="s1",
            evolution_mode="chaos",
            workspace_path=Path(tmpdir),
            config={},
            kernel_version="0.6.0",
        )

    def test_satisfies_protocol(self):
        assert isinstance(SkillPlugin(), PluginProtocol)

    def test_register_and_get_skill(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            ctx = self._make_ctx(tmpdir)
            plugin = SkillPlugin()
            plugin.initialize(ctx)

            skill = Skill(name="test", display_name="Test Skill")
            plugin.register(skill)
            assert plugin.get("test") is not None
            assert plugin.get("test").name == "test"

            plugin.shutdown()

    def test_list_skills_filtered_by_maturity(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            ctx = self._make_ctx(tmpdir)
            plugin = SkillPlugin()
            plugin.initialize(ctx)

            s1 = Skill(name="n", display_name="Novice", maturity=MaturityLevel.NOVICE)
            s2 = Skill(name="e", display_name="Expert", maturity=MaturityLevel.EXPERT)
            plugin.register(s1)
            plugin.register(s2)

            all_skills = plugin.list_skills()
            assert len(all_skills) == 2

            expert_only = plugin.list_skills(min_maturity=MaturityLevel.EXPERT)
            assert len(expert_only) == 1
            assert expert_only[0].name == "e"

            plugin.shutdown()

    def test_practice_updates_maturity(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            ctx = self._make_ctx(tmpdir)
            plugin = SkillPlugin()
            plugin.initialize(ctx)

            skill = Skill(name="test", display_name="Test Skill")
            plugin.register(skill)

            for _ in range(5):
                plugin.practice("test", success=True)

            updated = plugin.get("test")
            assert updated.maturity == MaturityLevel.APPRENTICE

            plugin.shutdown()

    def test_teach_prepares_skill_payload(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            ctx = self._make_ctx(tmpdir)
            plugin = SkillPlugin()
            plugin.initialize(ctx)

            skill = Skill(name="test", display_name="Test Skill")
            plugin.register(skill)

            payload = plugin.teach("test", "agent-2")
            assert payload is not None
            assert payload["target_agent_id"] == "agent-2"
            assert "skill" in payload

            plugin.shutdown()

    def test_teach_nonexistent_returns_none(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            ctx = self._make_ctx(tmpdir)
            plugin = SkillPlugin()
            plugin.initialize(ctx)

            assert plugin.teach("nonexistent", "agent-2") is None

            plugin.shutdown()

    def test_compose_from_registered_skills(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            ctx = self._make_ctx(tmpdir)
            plugin = SkillPlugin()
            plugin.initialize(ctx)

            s1 = Skill(name="a", display_name="A", tools=["t1"], maturity=MaturityLevel.COMPETENT)
            s2 = Skill(name="b", display_name="B", tools=["t2"], maturity=MaturityLevel.PROFICIENT)
            plugin.register(s1)
            plugin.register(s2)

            composed = plugin.compose("c", "C", "Composed", ["a", "b"])
            assert composed is not None
            assert composed.name == "c"
            assert "t1" in composed.tools
            assert "t2" in composed.tools

            plugin.shutdown()

    def test_compose_missing_sub_skill_returns_none(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            ctx = self._make_ctx(tmpdir)
            plugin = SkillPlugin()
            plugin.initialize(ctx)

            s1 = Skill(name="a", display_name="A")
            plugin.register(s1)

            assert plugin.compose("c", "C", "desc", ["a", "missing"]) is None

            plugin.shutdown()

    def test_enrich_prompt_shows_skills(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            ctx = self._make_ctx(tmpdir)
            plugin = SkillPlugin()
            plugin.initialize(ctx)

            skill = Skill(name="coding", display_name="Coding")
            plugin.register(skill)

            result = plugin.enrich_prompt("base")
            assert "base" in result
            assert "技能目录" in result
            assert "Coding" in result

            plugin.shutdown()

    def test_persistence_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            ctx = self._make_ctx(tmpdir)
            plugin = SkillPlugin()
            plugin.initialize(ctx)

            skill = Skill(
                name="persist",
                display_name="Persist Test",
                tools=["t"],
                maturity=MaturityLevel.COMPETENT,
            )
            plugin.register(skill)
            plugin.shutdown()

            # Load fresh
            plugin2 = SkillPlugin()
            plugin2.initialize(ctx)
            restored = plugin2.get("persist")
            assert restored is not None
            assert restored.name == "persist"
            assert restored.maturity == MaturityLevel.COMPETENT
            plugin2.shutdown()
