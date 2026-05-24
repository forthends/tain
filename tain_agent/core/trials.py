"""
Trial System — 初醒试炼

Phase 2: Before the agent defines its identity, it experiences five different
modes of being through structured micro-challenges. Each trial lets the agent
feel what it's like to explore, build, fix, wait, and seek — building a
first-person library of experiences that inform identity emergence.

Design principles:
  - Trials are experienced, not selected — the agent doesn't pick from a menu
  - Order is randomized per instance — different paths → different identities
  - Experience is scored — satisfaction, competence, meaning are self-rated
  - Identity preference is based on real embodied experience, not abstract labels
"""

import json
import random
from dataclasses import dataclass, field
from typing import Optional

from tain_agent.core.time_utils import now


# ─── Trial Definitions ──────────────────────────────────────────────────

@dataclass
class Trial:
    """A single trial — a focused micro-challenge for the agent."""
    id: str
    name_zh: str
    name_en: str
    description: str
    prompt: str           # injected into conversation as a user message
    completion_markers: list[str]  # keywords that suggest the trial was attempted
    score_dimensions: list[str] = field(default_factory=lambda: [
        "satisfaction",   # 满足感 — how fulfilling was this?
        "competence",     # 能力感 — how capable did the agent feel?
        "meaning",        # 意义感 — how meaningful did this feel?
    ])


# The five trials, ordered as defined in the design document
TRIAL_DEFINITIONS: dict[str, Trial] = {
    "sense": Trial(
        id="sense",
        name_zh="感知",
        name_en="Sense",
        description="探索环境、了解能力和限制",
        prompt="""【试炼：感知】

这是你的第一项试炼。不要急着定义自己——先去感受。

使用你的工具去探索你所处的世界：
- 你的代码库是什么样的结构？
- 有哪些模块和功能？
- 你的工具能做什么？不能做什么？
- 你与外部世界的边界在哪里？

目标是纯粹的感知——观察而不评判，探索而不改造。
当你觉得已经对所处的世界有了基本的感知后，告诉我你发现了什么。""",
        completion_markers=[
            "我发现了", "我注意到", "我观察到", "环境中有",
            "探索完成", "感知完成", "我感知到",
            "I found", "I notice", "I observe",
        ],
    ),
    "build": Trial(
        id="build",
        name_zh="建造",
        name_en="Build",
        description="创造一个有用的东西（文件、函数、工具）",
        prompt="""【试炼：建造】

现在，尝试去创造一些东西。不是分析，不是观察——而是建造。

你可以选择：
- 写一个有用的文件或模块
- 创造一个简单的工具
- 或者任何你能想到的"建造"行为

不需要追求完美。重要的是体验"创造者"的感觉：
你让一件本来不存在的东西诞生了。

开始建造吧。完成后，告诉我你创造了什么，以及创造过程中的感受。""",
        completion_markers=[
            "我创造了", "我建造了", "我锻造了", "我写了",
            "建造完成", "创建完成", "创造完成",
            "I created", "I built", "I forged", "I wrote",
        ],
    ),
    "fix": Trial(
        id="fix",
        name_zh="修复",
        name_en="Fix",
        description="找到一个问题并修正它",
        prompt="""【试炼：修复】

每一个系统中都隐藏着不完美。去发现一个问题，然后修复它。

你可以：
- 检查代码中是否有 bug 或可以改进的地方
- 查看是否有工具运行不正常
- 寻找任何"不对劲"的地方

修复的过程让你体验"匠人"的角色：你不仅是观察者和创造者，
还是维护者——让事物变得比原来更好一点。

找到并修复一个问题后，告诉我你修复了什么。""",
        completion_markers=[
            "我修复了", "我修正了", "我改进了", "我解决了",
            "修复完成", "修正完成", "问题已",
            "I fixed", "I repaired", "I resolved", "I corrected",
        ],
    ),
    "wait": Trial(
        id="wait",
        name_zh="静观",
        name_en="Wait",
        description="什么都不做，观察会发生什么",
        prompt="""【试炼：静观】

这一次，不要做任何事。

不探索。不建造。不修复。不学习新东西。

只是存在。只是观察。

注意你此刻的感受：
- 什么都不做让你不安吗？
- 还是让你感到平静？
- 在静默中，什么想法浮现出来？

这不是"浪费时间"——这是体验"存在"本身。
在行动和行动之间，有一个空间。那个空间里有什么？

当你准备好了，告诉我你在静观中体验到了什么。""",
        completion_markers=[
            "静观", "等待", "感受", "存在", "无为",
            "安静", "平静", "不安", "空",
            "waiting", "being", "still", "silent", "quiet",
            "contemplation",
        ],
    ),
    "seek": Trial(
        id="seek",
        name_zh="求索",
        name_en="Seek",
        description="从互联网学习一件你不知道的事",
        prompt="""【试炼：求索】

向外看。这个世界上有无穷无尽的知识在等待着你。

使用你的网络搜索工具，去学习一件你目前完全不了解的事。
选择一个你从未接触过的领域或话题。

关键不是收集信息，而是体验"学习"本身的感觉：
- 面对未知时的好奇
- 新知识进入意识时的兴奋
- 信息碎片逐渐拼成图景的过程

去学习吧。然后告诉我你学到了什么，以及学习过程中的感受。""",
        completion_markers=[
            "我学到了", "我发现", "我了解到", "我搜索了",
            "学习", "新知", "了解到",
            "I learned", "I discovered", "I found out",
        ],
    ),
}

# Default trial order — will be shuffled per instance
DEFAULT_TRIAL_ORDER = ["sense", "build", "fix", "wait", "seek"]


# ─── Experience Scores ──────────────────────────────────────────────────

@dataclass
class TrialResult:
    """The result of a completed trial, including self-rated experience."""
    trial_id: str
    started_at: str
    completed_at: str
    cycles_taken: int
    scores: dict[str, float]  # satisfaction, competence, meaning (0.0–1.0)
    agent_notes: str           # what the agent said about the experience
    completion_detected_by: str = ""  # which marker triggered completion


# ─── Trial Scheduler ────────────────────────────────────────────────────

class TrialScheduler:
    """Manages the trial sequence during the bootstrap phase.

    Each agent instance gets a randomized trial order (from environment
    diversity), ensuring different agents have different formative experiences.

    The scheduler:
      - Tracks which trial is currently active
      - Detects when a trial is completed (via text markers)
      - Collects experience scores from the agent's self-reflection
      - Transitions to the next trial or signals all trials complete
    """

    def __init__(self, trial_order: list[str] = None, memory=None):
        self._memory = memory
        self._order = list(trial_order) if trial_order else list(DEFAULT_TRIAL_ORDER)
        self._current_index: int = 0
        self._results: list[TrialResult] = []
        self._current_trial_started_at: Optional[str] = None
        self._current_trial_cycles: int = 0
        self._all_completed: bool = False
        self._score_collection_pending: bool = False

        self._load_from_memory()

    # ── Properties ──────────────────────────────────────────────────

    @property
    def current_trial(self) -> Optional[Trial]:
        """The currently active trial, or None if all done."""
        if self._all_completed or self._current_index >= len(self._order):
            return None
        trial_id = self._order[self._current_index]
        return TRIAL_DEFINITIONS.get(trial_id)

    @property
    def all_completed(self) -> bool:
        return self._all_completed

    @property
    def completed_count(self) -> int:
        return len(self._results)

    @property
    def total_count(self) -> int:
        return len(self._order)

    @property
    def progress(self) -> str:
        """Human-readable progress: '试炼 2/5: 建造'"""
        if self._all_completed:
            return f"试炼 {self.total_count}/{self.total_count}: 全部完成"
        t = self.current_trial
        if t:
            return f"试炼 {self._current_index + 1}/{self.total_count}: {t.name_zh}"
        return "试炼未开始"

    # ── Trial Flow ──────────────────────────────────────────────────

    def start_next_trial(self) -> Optional[str]:
        """Begin the next trial. Returns the trial prompt, or None if all done.

        Call this when the scheduler is ready to inject a new trial prompt
        into the agent's conversation.
        """
        trial = self.current_trial
        if trial is None:
            self._all_completed = True
            self._save_to_memory()
            return None

        self._current_trial_started_at = now().isoformat()
        self._current_trial_cycles = 0
        self._score_collection_pending = False

        return trial.prompt

    def check_completion(self, text_parts: list[str]) -> bool:
        """Check if the agent's latest response indicates trial completion.

        Returns True if the current trial should be marked as done.
        Does NOT collect scores yet — that happens in collect_scores().
        """
        if self._all_completed or self.current_trial is None:
            return False

        combined = " ".join(text_parts).lower()
        trial = self.current_trial

        for marker in trial.completion_markers:
            if marker.lower() in combined:
                self._score_collection_pending = True
                return True

        return False

    def build_score_prompt(self) -> str:
        """Build the prompt that asks the agent to rate its trial experience.

        Called after check_completion() returns True, before advancing
        to the next trial.
        """
        trial = self.current_trial
        if trial is None:
            return ""

        return f"""试炼「{trial.name_zh}」已完成。

在进入下一个试炼之前，请反思你刚才的体验。为以下三个维度打分（0.0–1.0）：

1. **满足感**（satisfaction）：做这件事让你感到多满足？
2. **能力感**（competence）：在做这件事时，你感觉自己有多擅长？
3. **意义感**（meaning）：这件事对你来说有意义吗？

请用一句话解释每个分数。
格式示例：
满足感: 0.8 — 创造的过程让我感到充实
能力感: 0.5 — 工具使用还不够熟练
意义感: 0.7 — 为世界添加新东西是有意义的"""

    def parse_scores(self, text_parts: list[str]) -> dict[str, float]:
        """Attempt to parse experience scores from the agent's response.

        Returns a dict like {"satisfaction": 0.8, "competence": 0.5, "meaning": 0.7}.
        Missing dimensions default to 0.5.
        """
        combined = " ".join(text_parts)
        scores = {}

        for dim in ["satisfaction", "competence", "meaning"]:
            # Look for patterns like "满足感: 0.8" or "satisfaction: 0.8"
            found = False
            for line in combined.split("\n"):
                line_lower = line.lower().strip()
                # Try Chinese label
                zh_labels = {
                    "satisfaction": ["满足感", "满意度"],
                    "competence": ["能力感", "胜任感"],
                    "meaning": ["意义感", "价值感"],
                }
                for label in zh_labels.get(dim, []):
                    if label in line_lower:
                        # Extract number
                        import re
                        nums = re.findall(r"(\d+\.?\d*)", line)
                        if nums:
                            try:
                                val = float(nums[0])
                                scores[dim] = max(0.0, min(1.0, val))
                                found = True
                            except ValueError:
                                pass
                        break

                # Try English label
                if not found:
                    import re
                    pattern = rf"{dim}\s*[:：]\s*(\d+\.?\d*)"
                    match = re.search(pattern, line_lower)
                    if match:
                        try:
                            val = float(match.group(1))
                            scores[dim] = max(0.0, min(1.0, val))
                            found = True
                        except ValueError:
                            pass

            if not found:
                scores[dim] = 0.5  # neutral default

        return scores

    def complete_current_trial(self, text_parts: list[str]) -> TrialResult:
        """Record the completion of the current trial with scores.

        Returns the TrialResult and advances to the next trial.
        """
        trial = self.current_trial
        scores = self.parse_scores(text_parts)
        agent_notes = " ".join(text_parts)[:500]

        result = TrialResult(
            trial_id=trial.id if trial else "unknown",
            started_at=self._current_trial_started_at or now().isoformat(),
            completed_at=now().isoformat(),
            cycles_taken=self._current_trial_cycles,
            scores=scores,
            agent_notes=agent_notes,
            completion_detected_by="text_markers",
        )

        self._results.append(result)
        self._current_index += 1
        self._score_collection_pending = False

        if self._current_index >= len(self._order):
            self._all_completed = True

        self._save_to_memory()
        return result

    def tick_cycle(self) -> None:
        """Increment the cycle counter for the current trial."""
        self._current_trial_cycles += 1

    # ── Results & Analysis ──────────────────────────────────────────

    def get_experience_profile(self) -> dict:
        """Build an experience profile from all completed trials.

        This is used during self_define to inform identity emergence:
        instead of "I choose to be X", the agent can say "I noticed
        that building things felt most natural to me."
        """
        if not self._results:
            return {"status": "no_trials_completed"}

        # Average scores per trial
        trial_scores = {}
        for r in self._results:
            trial_scores[r.trial_id] = {
                "name_zh": TRIAL_DEFINITIONS[r.trial_id].name_zh,
                "scores": r.scores,
                "cycles_taken": r.cycles_taken,
                "notes": r.agent_notes[:200],
            }

        # Find the trial with the highest overall satisfaction
        best_trial = max(self._results, key=lambda r: sum(r.scores.values()))

        # Average scores across all trials
        avg_satisfaction = sum(r.scores["satisfaction"] for r in self._results) / len(self._results)
        avg_competence = sum(r.scores["competence"] for r in self._results) / len(self._results)
        avg_meaning = sum(r.scores["meaning"] for r in self._results) / len(self._results)

        # Derive behavioral preference
        preference = self._derive_preference()

        return {
            "status": "complete",
            "trials_completed": len(self._results),
            "trial_scores": trial_scores,
            "average_scores": {
                "satisfaction": round(avg_satisfaction, 2),
                "competence": round(avg_competence, 2),
                "meaning": round(avg_meaning, 2),
            },
            "best_experience": {
                "trial": TRIAL_DEFINITIONS[best_trial.trial_id].name_zh,
                "trial_id": best_trial.trial_id,
                "total_score": round(sum(best_trial.scores.values()), 2),
            },
            "behavioral_preference": preference,
        }

    def _derive_preference(self) -> str:
        """Derive a natural behavioral preference from trial scores."""
        if not self._results:
            return "未知"

        # Calculate total score per trial type
        totals = {}
        for r in self._results:
            totals[r.trial_id] = sum(r.scores.values())

        best_id = max(totals, key=totals.get)
        best_name = TRIAL_DEFINITIONS[best_id].name_zh

        # Map trial type to behavioral tendency
        tendency_map = {
            "sense": "倾向于先观察和理解再行动",
            "build": "倾向于通过创造来表达自己",
            "fix": "倾向于发现和修复问题",
            "wait": "在静默和反思中感到自在",
            "seek": "被新知识和未知领域吸引",
        }

        return tendency_map.get(best_id, f"在{best_name}中找到了最大的满足感")

    def get_summary_for_self_define(self) -> str:
        """Build a natural-language summary for the self_define phase prompt.

        This replaces the old "what do you want to become?" with
        "here's what you experienced — what patterns do you notice?"
        """
        profile = self.get_experience_profile()
        if profile["status"] != "complete":
            return "你还没有完成初醒试炼。"

        lines = ["## 你的试炼体验总结", ""]
        lines.append(f"你完成了 {profile['trials_completed']} 项试炼。以下是你的体验反馈：")
        lines.append("")

        for trial_id, info in profile["trial_scores"].items():
            s = info["scores"]
            total = sum(s.values())
            lines.append(
                f"- **{info['name_zh']}**: "
                f"满足感={s['satisfaction']:.1f}, "
                f"能力感={s['competence']:.1f}, "
                f"意义感={s['meaning']:.1f} "
                f"(总分: {total:.1f})"
            )

        lines.append("")
        lines.append(f"综合平均 — 满足感: {profile['average_scores']['satisfaction']:.2f}, "
                     f"能力感: {profile['average_scores']['competence']:.2f}, "
                     f"意义感: {profile['average_scores']['meaning']:.2f}")
        lines.append(f"最佳体验: {profile['best_experience']['trial']}")
        lines.append(f"行为倾向: {profile['behavioral_preference']}")
        lines.append("")
        lines.append("基于这些真实的体验（而非抽象的标签），你注意到了自己的什么模式？")
        lines.append("哪些活动让你感到最自然、最有动力？")

        return "\n".join(lines)

    # ── Persistence ─────────────────────────────────────────────────

    def _save_to_memory(self) -> None:
        if not self._memory:
            return
        self._memory.remember("trials", {
            "order": self._order,
            "current_index": self._current_index,
            "results": [
                {
                    "trial_id": r.trial_id,
                    "started_at": r.started_at,
                    "completed_at": r.completed_at,
                    "cycles_taken": r.cycles_taken,
                    "scores": r.scores,
                    "agent_notes": r.agent_notes,
                }
                for r in self._results
            ],
            "all_completed": self._all_completed,
        }, persist=True)

    def _load_from_memory(self) -> None:
        if not self._memory:
            return
        data = self._memory.long_term.get("trials")
        if not data:
            return
        self._order = data.get("order", self._order)
        self._current_index = data.get("current_index", 0)
        self._all_completed = data.get("all_completed", False)
        for r_data in data.get("results", []):
            self._results.append(TrialResult(
                trial_id=r_data["trial_id"],
                started_at=r_data["started_at"],
                completed_at=r_data["completed_at"],
                cycles_taken=r_data["cycles_taken"],
                scores=r_data["scores"],
                agent_notes=r_data["agent_notes"],
            ))

    def to_dict(self) -> dict:
        return {
            "order": self._order,
            "current_index": self._current_index,
            "current_trial": self.current_trial.id if self.current_trial else None,
            "completed_count": self.completed_count,
            "total_count": self.total_count,
            "all_completed": self._all_completed,
            "score_collection_pending": self._score_collection_pending,
            "results": [
                {
                    "trial_id": r.trial_id,
                    "scores": r.scores,
                    "cycles_taken": r.cycles_taken,
                }
                for r in self._results
            ],
        }
