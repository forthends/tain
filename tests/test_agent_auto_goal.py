"""Tests for automatic goal generation from drive pressure."""
import pytest
from tain_agent.core.drives import DriveSystem
from tain_agent.evolution.goal import GoalSystem


class FakeConversation:
    def __init__(self):
        self.messages = []

    def append(self, role, content):
        self.messages.append((role, content))

    def len(self):
        return len(self.messages)

    def checkpoint_if_needed(self):
        return None

    def trim_to_token_budget(self, keep_last=40):
        pass


class FakeDecisionLog:
    def __init__(self):
        self.records = []

    def record(self, **kwargs):
        self.records.append(kwargs)
        return "fake-id"

    def flush(self):
        pass


class TestAutoGoalGeneration:
    def test_goal_created_when_exploration_high_and_no_active_goals(self):
        ds = DriveSystem(drives_config={
            "curiosity": 0.9, "mastery": 0.3, "creation": 0.4, "conservation": 0.2,
        })
        ds._idle_cycles = 50
        ds._days_since_last_action = 10.0  # boost idle pressure for > 0.7 total
        gs = GoalSystem()
        conv = FakeConversation()
        dl = FakeDecisionLog()

        exploration = ds.compute_exploration_score()
        assert exploration > 0.7
        assert gs.list_active() == []

        dominant = ds.dominate_drive()
        assert dominant == "curiosity"

        templates = {
            "curiosity": ("探索并了解 {domain} 的基本概念和应用",
                         "产出至少一份知识摘要或理解 3+ 个核心概念"),
            "mastery": ("深入优化 {domain} 的性能或代码质量",
                       "代码变更通过测试，或性能指标有可测量提升"),
            "creation": ("锻造一个新工具来填补 {domain}",
                        "工具通过 forge -> test 闭环并被注册"),
            "conservation": ("审查和整理 {domain} 的现有状态并产出审计报告",
                           "产出一份结构化的审计报告或维护记录"),
        }
        desc_tpl, criteria = templates[dominant]
        domain = ds.get_target_domain()
        description = desc_tpl.format(domain=domain)

        goal = gs.create_goal(description, criteria)
        assert goal is not None
        assert goal.status == "pending"
        assert len(gs.list_active()) == 1

        prompt = (
            f"[自主目标] 你的 {dominant} 驱动力高涨，系统自动为你创建了一个目标：\n"
            f"  -> {description}\n"
            f"  成功标准：{criteria}\n"
            f"你可以通过 set_goal 工具调整或替换这个目标。"
        )
        conv.append("user", prompt)
        dl.record(
            context={"action": "auto_generate_goal", "drive": dominant},
            decision_type="auto_goal",
            options_considered=[{"option": "auto_generate_goal",
                                 "drive": dominant}],
            chosen_option=goal.id,
            reasoning=f"Exploration score {exploration:.3f} > 0.7, "
                      f"no active goals, dominant drive: {dominant}",
            expected_outcome=description,
            phase="work",
        )

        assert any("自主目标" in msg for _, msg in conv.messages)

    def test_no_goal_when_active_goals_exist(self):
        ds = DriveSystem(drives_config={
            "curiosity": 0.9, "mastery": 0.3, "creation": 0.4, "conservation": 0.2,
        })
        ds._idle_cycles = 50
        gs = GoalSystem()
        gs.create_goal("existing goal", "criteria")
        assert len(gs.list_active()) == 1

    def test_no_goal_when_exploration_low(self):
        ds = DriveSystem(drives_config={
            "curiosity": 0.2, "mastery": 0.5, "creation": 0.3, "conservation": 0.4,
        })
        ds._idle_cycles = 0
        gs = GoalSystem()
        exploration = ds.compute_exploration_score()
        assert exploration <= 0.7
