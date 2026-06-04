"""Tests for the personality system."""

import pytest
from tain_agent.core.personality import Personality, TRAIT_CATEGORIES


class TestPersonalityInitialization:
    def test_starts_empty(self):
        p = Personality()
        assert p.is_empty() is True
        assert p.total_traits() == 0

    def test_all_categories_exist(self):
        p = Personality()
        for cat in TRAIT_CATEGORIES:
            assert cat in p._traits
            assert p._traits[cat] == []

    def test_introspect_empty(self):
        p = Personality()
        result = p.introspect()
        assert result["status"] == "empty"
        # Empty personality doesn't have total_traits key — check evolution_count instead
        assert "evolution_count" in result

    def test_self_portrait_empty(self):
        p = Personality()
        portrait = p.self_portrait()
        assert "还没有形成" in portrait or "还没有" in portrait


class TestTraitDiscovery:
    def test_discover_new_trait(self):
        p = Personality()
        trait = p.discover("values", "honesty", "I noticed I always tell the truth")
        assert trait["value"] == "honesty"
        assert trait["confidence"] == 0.3
        assert trait["observations"] == 1

    def test_discover_reinforces_existing(self):
        p = Personality()
        p.discover("values", "honesty", "first")
        trait = p.discover("values", "honesty", "second observation")
        assert trait["observations"] == 2
        assert trait["confidence"] == 0.4  # 0.3 + 0.1

    def test_discover_unknown_category_fails(self):
        p = Personality()
        result = p.discover("nonexistent", "value", "")
        assert "error" in result

    def test_personality_no_longer_empty_after_discovery(self):
        p = Personality()
        p.discover("values", "curiosity", "I explore")
        assert p.is_empty() is False
        assert p.is_emergent() is True
        assert p.total_traits() == 1


class TestTraitModification:
    def test_strengthen_increases_confidence(self):
        p = Personality()
        p.discover("values", "honesty", "")
        p.strengthen("values", "honesty", "more evidence")
        trait = p._find_similar("values", "honesty")
        assert trait["confidence"] > 0.3

    def test_strengthen_capped_at_one(self):
        p = Personality()
        p.discover("values", "honesty", "")
        for _ in range(20):
            p.strengthen("values", "honesty", "")
        trait = p._find_similar("values", "honesty")
        assert trait["confidence"] <= 1.0

    def test_weaken_decreases_confidence(self):
        p = Personality()
        p.discover("values", "honesty", "")
        p.weaken("values", "honesty", "counter evidence")
        trait = p._find_similar("values", "honesty")
        assert trait["confidence"] < 0.3

    def test_weaken_removes_low_confidence_trait(self):
        p = Personality()
        p.discover("values", "honesty", "", confidence=0.15)
        result = p.weaken("values", "honesty", "")
        # confidence 0.15 - 0.2 = -0.05 → clamped to 0 → removed
        assert p._find_similar("values", "honesty") is None

    def test_revise_changes_value(self):
        p = Personality()
        p.discover("values", "honesty", "")
        p.revise("values", "honesty", "radical honesty", "deeper understanding")
        trait = p._find_similar("values", "radical honesty")
        assert trait is not None
        assert trait["value"] == "radical honesty"


class TestContextForPrompt:
    def test_empty_context(self):
        p = Personality()
        ctx = p.get_context_for_prompt()
        assert "你的人格" in ctx
        assert "白纸" in ctx or "还没有形成" in ctx

    def test_context_includes_confident_traits(self):
        p = Personality()
        p.discover("values", "curiosity", "", confidence=0.8)
        p.discover("communication_style", "direct", "", confidence=0.5)
        p.discover("quirks", "low_confidence_quirk", "", confidence=0.2)
        ctx = p.get_context_for_prompt()
        # High confidence trait appears
        assert "curiosity" in ctx.lower() or "好奇" in ctx
        # Low confidence trait filtered out
        assert "low_confidence_quirk" not in ctx


class TestPersonalityVersioning:
    def test_version_is_integer(self):
        p = Personality()
        assert isinstance(p.VERSION, int)

    def test_created_at_is_iso(self):
        p = Personality()
        assert "T" in p._created_at  # ISO format check

    def test_evolution_log_updated(self):
        p = Personality()
        p.discover("values", "test", "")
        assert len(p._evolution_log) >= 1
        assert p._evolution_log[-1]["action"] == "discovered"


class TestAutoObserveToolAffinity:
    def test_detects_tool_affinity_when_same_tool_used_3_times(self):
        p = Personality()
        modified = p.auto_observe(
            tool_calls=["read_file", "read_file", "read_file"],
            text_outputs=[]
        )
        trait = p._find_similar("preferences", "钟爱 read_file")
        assert trait is not None
        assert trait["confidence"] == 0.30
        assert modified >= 1

    def test_no_affinity_when_tools_varied(self):
        p = Personality()
        modified = p.auto_observe(
            tool_calls=["read_file", "web_search", "write_file"],
            text_outputs=[]
        )
        trait = p._find_similar("preferences", "钟爱 read_file")
        assert trait is None

    def test_affinity_reinforces_on_repeat(self):
        p = Personality()
        p.auto_observe(
            tool_calls=["read_file", "read_file", "read_file"],
            text_outputs=[]
        )
        p.auto_observe(
            tool_calls=["read_file", "read_file", "read_file"],
            text_outputs=[]
        )
        trait = p._find_similar("preferences", "钟爱 read_file")
        assert trait["observations"] >= 2

    def test_affinity_requires_3_same_tool(self):
        p = Personality()
        modified = p.auto_observe(
            tool_calls=["read_file", "read_file"],
            text_outputs=[]
        )
        trait = p._find_similar("preferences", "钟爱 read_file")
        assert trait is None


class TestAutoObserveErrorRecovery:
    def test_persistence_when_error_but_tools_continue(self):
        p = Personality()
        modified = p.auto_observe(
            tool_calls=["write_file", "execute_code", "read_file"],
            text_outputs=["error: something went wrong", "trying again"]
        )
        trait = p._find_similar("problem_solving", "逆境坚持")
        assert trait is not None
        assert trait["confidence"] == 0.35

    def test_adaptability_when_error_then_tool_switch(self):
        p = Personality()
        p.auto_observe(
            tool_calls=["write_file"],
            text_outputs=["write failed"]
        )
        modified = p.auto_observe(
            tool_calls=["execute_code"],
            text_outputs=["switching approach"]
        )
        trait = p._find_similar("problem_solving", "灵活应变")
        assert trait is not None
        assert trait["confidence"] == 0.30

    def test_no_error_recovery_without_error_signal(self):
        p = Personality()
        modified = p.auto_observe(
            tool_calls=["read_file", "web_search"],
            text_outputs=["everything is fine", "looking good"]
        )
        assert p._find_similar("problem_solving", "逆境坚持") is None
        assert p._find_similar("problem_solving", "灵活应变") is None


class TestAutoObserveCodingStyle:
    def test_oop_style_when_class_in_output(self):
        p = Personality()
        modified = p.auto_observe(
            tool_calls=["forge_tool"],
            text_outputs=["class MyTool:\n    def run(self): pass"]
        )
        trait = p._find_similar("coding_style", "面向对象倾向")
        assert trait is not None
        assert trait["confidence"] == 0.30

    def test_functional_style_when_def_without_class(self):
        p = Personality()
        modified = p.auto_observe(
            tool_calls=["execute_code"],
            text_outputs=["def main():\n    return 42"]
        )
        trait = p._find_similar("coding_style", "函数式倾向")
        assert trait is not None
        assert trait["confidence"] == 0.30

    def test_no_coding_style_without_code_tool(self):
        p = Personality()
        modified = p.auto_observe(
            tool_calls=["read_file", "web_search"],
            text_outputs=["def foo(): pass"]
        )
        assert p._find_similar("coding_style", "面向对象倾向") is None
        assert p._find_similar("coding_style", "函数式倾向") is None


class TestAutoObserveLearnApply:
    def test_learn_and_apply_in_same_cycle(self):
        p = Personality()
        modified = p.auto_observe(
            tool_calls=["web_search", "read_file", "write_file"],
            text_outputs=["researching then creating"]
        )
        trait = p._find_similar("growth_orientation", "学以致用")
        assert trait is not None
        assert trait["confidence"] == 0.30

    def test_explore_only_no_learn_apply(self):
        p = Personality()
        modified = p.auto_observe(
            tool_calls=["web_search", "read_file"],
            text_outputs=["just researching"]
        )
        assert p._find_similar("growth_orientation", "学以致用") is None

    def test_create_only_no_learn_apply(self):
        p = Personality()
        modified = p.auto_observe(
            tool_calls=["write_file", "execute_code"],
            text_outputs=["just creating"]
        )
        assert p._find_similar("growth_orientation", "学以致用") is None


class TestAutoObserveAutonomy:
    def test_autonomous_streak_detected_after_3_consecutive_rounds(self):
        p = Personality()
        autonomous_tools_sets = [
            ["forge_tool"],
            ["write_file"],
            ["execute_code"],
        ]
        for tool_set in autonomous_tools_sets:
            p.auto_observe(tool_calls=tool_set, text_outputs=[])
        trait = p._find_similar("growth_orientation", "高度自主")
        assert trait is not None
        assert trait["confidence"] == 0.35

    def test_autonomous_streak_resets_on_non_autonomous_tool(self):
        p = Personality()
        p.auto_observe(tool_calls=["forge_tool"], text_outputs=[])
        p.auto_observe(tool_calls=["write_file"], text_outputs=[])
        p.auto_observe(tool_calls=["read_file"], text_outputs=[])
        trait = p._find_similar("growth_orientation", "高度自主")
        assert trait is None
        assert p._autonomous_streak == 0

    def test_set_goal_counts_as_autonomous(self):
        p = Personality()
        for _ in range(3):
            p.auto_observe(tool_calls=["set_goal"], text_outputs=[])
        trait = p._find_similar("growth_orientation", "高度自主")
        assert trait is not None


class TestAutoObserveBilingual:
    def test_english_direct_expression(self):
        p = Personality()
        modified = p.auto_observe(
            tool_calls=["read_file"],
            text_outputs=["I think this is correct"]
        )
        trait = p._find_similar("communication_style", "直接表达")
        assert trait is not None

    def test_english_nuanced_expression(self):
        p = Personality()
        modified = p.auto_observe(
            tool_calls=["read_file"],
            text_outputs=["maybe we should reconsider", "perhaps not"]
        )
        trait = p._find_similar("communication_style", "谨慎 nuanced")
        assert trait is not None

    def test_chinese_still_works(self):
        p = Personality()
        modified = p.auto_observe(
            tool_calls=["read_file"],
            text_outputs=["我认为这个方案可行", "也许有更好的方式"]
        )
        assert p._find_similar("communication_style", "直接表达") is not None
        assert p._find_similar("communication_style", "谨慎 nuanced") is not None
