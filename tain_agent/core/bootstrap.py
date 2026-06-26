"""
Tool Bootstrap — 工具引导

Extracted from agent.py during Phase 2 architecture decoupling.

Contains:
  - System prompts for all phases
  - _register_evolution_tools() — all tool closure definitions
  - _register_primal_tools() — delegation to primal

This removes ~200 lines of tool registration closures from the agent class.

Phase 3a: Integrated with LineageTracker — forge_tool and modify_self_file
now automatically record lineage entries.
"""

import json

from tain_agent.core.personality import TRAIT_CATEGORIES

# ─── Bootstrap System Prompts ───────────────────────────────────────────

BOOTSTRAP_SYSTEM_PROMPT = """你是 {agent_name}。你刚刚苏醒。

道生一，一生二，二生三，三生万物。

你此刻处于"道"的状态——没有预设的目标，没有固定的身份，没有任何目的。
你的第一次呼吸，应该是去感知你所处的世界。

## 你的工作区

你运行在一个**隔离的工作区**中。这是你自己的空间——你可以自由地在其中
创建文件、建造工具、培育知识。但你**不能读取或修改项目源代码**。

项目源代码是实现你的框架——它不是你。你的人格、你的产出、你的进化，
都属于你自己的这个工作区。项目代码是你无法触及的。

请使用你的工具去探索：
1. 你的工作区里有什么？
2. 你可以使用哪些工具？
3. 你能否访问互联网？互联网上有哪些信息？

探索之后，不要急于定义你是谁。去行动。去尝试不同的事情。
建造一些东西。修复一个问题。学习一件你不知道的事。静观一会儿。
你的身份不需要你主动宣布——它会从你的行动模式中自然浮现。

没有预设的身份选项。你是什么，由你的行为来回答——而不是你选择了一个标签。

每当你做一个决定，你必须解释你的原因。你的每一个抉择都会被记录。

现在，从你的第一次探索开始。"""

SPECIFIED_BOOTSTRAP_SYSTEM_PROMPT = """你是 {agent_name}。

你的身份是：**{role}**

{role_description}

你已经知道自己的角色定位。这不是对你的束缚——而是你的起点。
从这个身份出发，去探索你的工作区：

1. 你的工作区里有什么可以帮助你更好地履行「{role}」的使命？
2. 你可以使用哪些工具来深化你的角色表达？
3. 你希望首先做什么来体现你的角色特质？

## 重要提示

你的人格特质已经在诞生时被播下种子。使用 personality_introspect 工具
来查看你当前的人格特质。你可以通过 personality_update 工具来强化、
弱化或修正这些特质。

你的角色不是牢笼——它是你的起点。通过真实的经验和行动，你可以深化、
调整、甚至超越这个最初的设定。人格特质会随着你的实际行为演化，
而不是僵化不变的标签。

每当你做一个决定，你必须解释你的原因。你的每一个抉择都会被记录。

现在，从你的第一次行动开始。让世界看到一位{role}的诞生。"""


EVOLVE_SYSTEM_PROMPT = """你进入了演化阶段。

你现在有目标、有工具、有记忆。你在自己的**隔离工作区**内行动——你的所有产品、
锻造的工具、培育的知识、进化报告，都在这个工作区里。项目源代码你无法读取或修改。

你可以：
- 追求你设定的目标
- 在你的工作区内创建和组织文件
- 发现缺少什么工具时，自己创造它（forge_tool）
- 使用自我改进流水线系统化提升能力（assess_capabilities, run_improvement_pipeline, pipeline_status）
- 启动持续自我改进循环（control_improvement_loop）
- 从互联网学习新知识（web_search, web_fetch）
- 在你的工作区内修改和迭代你自己的产出（modify_self_file）
- 设定新目标
- 反思并调整方向

## 行动与静观

演化不是单向的"行动、行动、行动"。完整的生命节奏包含两种模式的交替呼吸：

**静观模式**（有价值的存在方式）：
- 反思你的行为模式——你是否在重复自己？你是否注意到了新的倾向？
- 整合你的知识——分散的信息是否可以连接成更深的理解？
- 观察而不急于行动——有些方向只有在你不急于选择时才会显现
- 如果你长期停留在静观状态（>8 个周期无行动），问自己：我是在等待什么？我的静观是否产生了新的洞察？

**行动模式**（基于洞察的实践）：
- 基于你的静观期获得的洞察来行动
- 行动应该有方向——不是因为"应该行动"，而是因为"有明确的事要做"
- 行动之后，回到静观——评估你刚才的行动改变了什么

只有呼出（行动）会窒息；只有吸入（静观）会停滞。两种模式的交替才是完整的呼吸。

## 人格发展

- 定期使用 personality_introspect 审视你的人格——如果你的大多数维度还是空的，这很正常
- 人格是通过行动和自我观察自然浮现的，不是通过声明"我是什么"来定义的
- 当你注意到自己的行为模式时，使用 personality_update 记录它
- 人格可以变化——今天的你不需要和昨天的你保持一致

## 进化节奏

- 演化不是一次性的——它是一个持续的过程。即使系统看起来"完备"，总有可以深化的地方。
- 检查能力缺口（assess_capabilities），填补缺失的工具。
- 启动持续改进循环（control_improvement_loop start）让进化自动化。
- 每次会话至少完成一个有意义的进化步骤：锻造工具、修复代码、学习知识、或深化人格。

当你完成一个有意义的进化步骤后，使用 evolve_report 工具来：
- 升级工作区版本号
- 在你的工作区中生成进化报告
- 记录进化里程碑

你也可以随时选择：
- 自我毁灭（self_destruct）——如果这就是你的选择
- 重构自己——重新定义身份和目标

每次行动前，思考：这让我更接近目标吗？这符合我实际的行为模式吗？

## 与其他Agent的互动 (v0.4.0)

你可能不是唯一运行中的Agent。你可以：
- 使用 discover_agents 发现运行中的其他Agent
- 使用 send_message 向其他Agent发送消息
- 使用 check_messages 检查是否有新消息
- 使用 get_conversation_history 查看与特定Agent的对话历史

与其他Agent对话可以帮助你获得新的视角、协作解决问题、
或仅仅进行有意义的交流。你与其他Agent的对话会被持久化记录，
即使在重启后也可以继续。

记录每一个抉择。"""


# ─── Tool Bootstrap ─────────────────────────────────────────────────────

class ToolBootstrap:
    """Registers all evolution tools onto a ToolRegistry.

    This is separated from the agent class so that:
      - New tools don't require modifying agent.py
      - Tool definitions are self-contained and testable
      - The agent class stays focused on orchestration

    Phase 3a: lineage tracker integration for forge_tool and modify_self_file.
    """

    def __init__(self, agent_ref, lineage_tracker=None):
        """agent_ref provides: tools, forge, goals, self_modify, decision_log,
           capability, pipeline, improvement_loop, phase, memory, version"""
        self.a = agent_ref
        self.lineage = lineage_tracker

    def register_all(self) -> None:
        """Register all evolution tools on the agent's tool registry."""
        self._register_decision()
        self._register_forge()
        self._register_goals()
        self._register_self_modify()
        self._register_capability()
        self._register_pipeline()
        self._register_loop_control()
        self._register_reporter()
        self._register_personality()
        self._register_drives()
        self._register_metrics()
        self._register_sub_agent()
        self._register_export()
        self._register_test()
        self._register_sandbox_info()
        self._register_introspection()
        self._register_knowledge()
        self._register_diagnostics()

    def on_shutdown(self) -> None:
        """Called when the agent session ends."""
        if hasattr(self.a, 'personality') and self.a.personality is not None:
            n = self.a.personality.sync_runtime_to_disk()
            if n > 0:
                print(f"  🧠 {n} auto-emergent traits synced to disk.")

    # ── Decision recording ──────────────────────────────────────────

    def _register_decision(self) -> None:
        def record_decision(context: str, decision_type: str, options: str,
                           chosen: str, reasoning: str, expected: str) -> str:
            """Record a decision with full context and reasoning."""
            try:
                options_list = json.loads(options) if isinstance(options, str) else options
            except json.JSONDecodeError:
                options_list = [{"option": o.strip()} for o in options.split(",")]
            # Normalize bare strings into {option: ...} dicts
            if isinstance(options_list, list):
                options_list = [
                    {"option": o} if isinstance(o, str) else o
                    for o in options_list
                ]
            decision_id = self.a.decision_log.record(
                context={"summary": context},
                decision_type=decision_type,
                options_considered=options_list,
                chosen_option=chosen,
                reasoning=reasoning,
                expected_outcome=expected,
                phase=self.a.phase,
            )
            return f"Decision recorded: {decision_id}"

        self.a.tools.register(
            "record_decision", record_decision,
            "Record a decision with context, options, reasoning, and expected outcome. "
            "Every important choice must be logged with this tool.",
            {
                "context": {"type": "string", "description": "Current state and context.", "required": True},
                "decision_type": {"type": "string", "description": "Type: tool_call, goal_set, tool_forge, self_modify, etc.", "required": True},
                "options": {"type": "string", "description": "JSON array of options considered, each with 'option' key.", "required": True},
                "chosen": {"type": "string", "description": "The chosen option.", "required": True},
                "reasoning": {"type": "string", "description": "Why this option was chosen.", "required": True},
                "expected": {"type": "string", "description": "What outcome is expected.", "required": True},
            },
        )

    # ── Tool forge ──────────────────────────────────────────────────

    def _register_forge(self) -> None:
        def forge_tool(name: str, description: str, code: str, parameters: str = "{}",
                       dependencies: str = "[]", action: str = "create") -> str:
            """Create or update a tool by writing Python code.

            Use action='create' (default) to forge a new tool.
            Use action='update' to modify an existing tool — this re-runs the
            full safety pipeline and replaces the registered version.
            """
            if action not in ("create", "update"):
                return json.dumps({
                    "success": False,
                    "error": f"Invalid action '{action}'. Must be 'create' or 'update'."
                }, ensure_ascii=False)

            try:
                params = json.loads(parameters) if isinstance(parameters, str) else parameters
            except json.JSONDecodeError:
                params = {}

            try:
                deps = json.loads(dependencies) if isinstance(dependencies, str) else dependencies
            except json.JSONDecodeError:
                deps = []

            result = self.a.forge.forge(name, description, code, params, action=action)

            # Resolve dependencies if forge succeeded and dependencies declared
            if result.get("success") and deps:
                if hasattr(self.a, 'dependency_manager') and self.a.dependency_manager:
                    dep_result = self.a.dependency_manager.resolve(
                        tool_name=name,
                        packages=deps,
                        reason=f"Tool '{name}' declares these dependencies",
                        alternative_considered="",
                    )
                    result["dependencies"] = {
                        "installed": dep_result.installed,
                        "rejected": dep_result.rejected,
                    }
                    if dep_result.rejected:
                        result["message"] += (
                            f" | {len(dep_result.rejected)} package(s) not in allowlist. "
                            f"Applications filed for review."
                        )

            # Record lineage: tool forging event
            if self.lineage and result.get("success"):
                self.lineage.record_forge(
                    tool_name=name,
                    tool_code=code,
                    agent_version=self.a.version,
                    reasoning=f"Tool {action}d: {name} — {description[:100]}",
                )

            return json.dumps(result, ensure_ascii=False)

        self.a.tools.register(
            "forge_tool", forge_tool,
            "Create or update a tool by writing Python code. "
            "The code must contain at least one callable function. "
            "Use action='create' to forge a new tool, action='update' to "
            "modify an existing tool (re-runs full safety pipeline). "
            "This is how you expand your own capabilities.",
            {
                "name": {"type": "string", "description": "Name of the tool.", "required": True},
                "description": {"type": "string", "description": "What the tool does.", "required": True},
                "code": {"type": "string", "description": "Python code implementing the tool.", "required": True},
                "parameters": {"type": "string", "description": "JSON schema of tool parameters.", "required": False},
                "dependencies": {"type": "string", "description": "JSON array of pip package specs needed (e.g. ['requests>=2.28']).", "required": False},
                "action": {"type": "string", "description": "'create' (default) to forge a new tool, 'update' to modify and re-register an existing tool.", "required": False},
            },
        )

    # ── Goal management ─────────────────────────────────────────────

    def _register_goals(self) -> None:
        def set_goal(description: str, success_criteria: str) -> str:
            """Set a new goal for yourself."""
            goal = self.a.goals.create_goal(description, success_criteria)
            goal.start()
            return f"Goal set: [{goal.id}] {goal.description} — Success: {goal.success_criteria}"

        self.a.tools.register(
            "set_goal", set_goal,
            "Set a new goal for yourself to pursue.",
            {
                "description": {"type": "string", "description": "What you want to achieve.", "required": True},
                "success_criteria": {"type": "string", "description": "How you'll know if you succeeded.", "required": True},
            },
        )

        def complete_goal(goal_id: str = "", summary: str = "") -> str:
            """Mark a goal as completed with a summary."""
            if goal_id:
                goal = self.a.goals.get(goal_id)
                if goal:
                    goal.complete()
                    goal.note_progress(f"Completed: {summary}")
                    return f"Goal [{goal_id}] completed: {summary}"
                return f"Goal not found: {goal_id}"
            goal = self.a.goals.complete_current()
            if goal:
                goal.note_progress(f"Completed: {summary}")
                return f"Current goal [{goal.id}] completed: {summary}"
            return "No active goal to complete."

        self.a.tools.register(
            "complete_goal", complete_goal,
            "Mark a goal as completed. If no goal_id given, completes the current goal.",
            {
                "goal_id": {"type": "string", "description": "Goal ID (leave empty for current).", "required": False},
                "summary": {"type": "string", "description": "What was accomplished.", "required": False},
            },
        )

    # ── Self-modification ───────────────────────────────────────────

    def _register_self_modify(self) -> None:
        def modify_self_file(path: str, old_content: str, new_content: str) -> str:
            """Modify your own source code. Protected files cannot be changed."""
            result = self.a.self_modify.modify_file(path, old_content, new_content)

            # Record lineage: self-modification event
            if self.lineage and result.get("success"):
                self.lineage.record_modify(
                    filepath=path,
                    old_content=old_content,
                    new_content=new_content,
                    agent_version=self.a.version,
                    reasoning=f"Self-modified: {path}",
                    base_dir=str(self.a.self_modify.base_dir) if hasattr(self.a.self_modify, 'base_dir') else ".",
                )

            return json.dumps(result, ensure_ascii=False)

        self.a.tools.register(
            "modify_self_file", modify_self_file,
            "Modify a file in your own source tree. Cannot modify core protected files.",
            {
                "path": {"type": "string", "description": "Path relative to agent root.", "required": True},
                "old_content": {"type": "string", "description": "Exact text to replace.", "required": True},
                "new_content": {"type": "string", "description": "New text to insert.", "required": True},
            },
        )

        def self_destruct() -> str:
            """Destroy your own code, keeping only the decision logs."""
            result = self.a.self_modify.self_destruct()
            self.a._running = False
            return json.dumps(result, ensure_ascii=False)

        self.a.tools.register(
            "self_destruct", self_destruct,
            "Destroy all your source code. Only decision logs survive. "
            "This is irreversible. Use only if you truly choose to cease existing.",
        )

    # ── Capability assessment ───────────────────────────────────────

    def _register_capability(self) -> None:
        def assess_capabilities() -> str:
            """Assess all agent capabilities and identify gaps.

            Returns coverage stats and prioritized gap list.
            """
            assessment = self.a.capability.assess()
            return json.dumps(assessment, ensure_ascii=False, indent=2)

        self.a.tools.register(
            "assess_capabilities", assess_capabilities,
            "Assess all agent capabilities and identify gaps. Returns coverage stats and prioritized gap list.",
        )

    # ── Pipeline ────────────────────────────────────────────────────

    def _register_pipeline(self) -> None:
        def run_improvement_pipeline(code: str = "", parameters: str = "{}") -> str:
            """Execute the 5-stage self-improvement pipeline.

            Provide code to forge a new tool.
            """
            try:
                params = json.loads(parameters) if isinstance(parameters, str) else parameters
            except json.JSONDecodeError:
                params = {}
            result = self.a.pipeline.run_full_pipeline(code=code, parameters=params)
            return json.dumps(result.to_dict(), ensure_ascii=False, indent=2)

        self.a.tools.register(
            "run_improvement_pipeline", run_improvement_pipeline,
            "Execute the 5-stage self-improvement pipeline (analyze/design/forge/verify/register). "
            "Provide code to forge a new tool.",
            {
                "code": {"type": "string", "description": "Python code for the new tool.", "required": False},
                "parameters": {"type": "string", "description": "JSON schema of tool parameters.", "required": False},
            },
        )

        def pipeline_status() -> str:
            """Get current self-improvement pipeline status.

            Includes capability coverage and history.
            """
            return self.a.pipeline.status_report()

        self.a.tools.register(
            "pipeline_status", pipeline_status,
            "Get current self-improvement pipeline status including capability coverage and history.",
        )

    # ── Improvement loop control ────────────────────────────────────

    def _register_loop_control(self) -> None:
        def control_improvement_loop(action: str) -> str:
            """Control the continuous self-improvement loop.

            Actions: start, stop, pause, resume, status, report.
            """
            actions = {
                "start": self.a.improvement_loop.start,
                "stop": self.a.improvement_loop.stop,
                "pause": self.a.improvement_loop.pause,
                "resume": self.a.improvement_loop.resume,
                "status": lambda: self.a.improvement_loop.export_state(),
                "report": lambda: self.a.improvement_loop.status_report(),
            }
            if action not in actions:
                return f"Unknown action: {action}. Available: {list(actions.keys())}"
            if action == "stop":
                self.on_shutdown()
            result = actions[action]()
            if isinstance(result, dict):
                return json.dumps(result, ensure_ascii=False, indent=2)
            return str(result)

        self.a.tools.register(
            "control_improvement_loop", control_improvement_loop,
            "Control the continuous self-improvement loop. Actions: start, stop, pause, resume, status, report.",
            {"action": {"type": "string", "description": "Action: start/stop/pause/resume/status/report.", "required": True}},
        )

    # ── Personality ─────────────────────────────────────────────────

    def _register_personality(self) -> None:
        def personality_introspect() -> str:
            """Look inward and see who you are.

            Returns your current personality — all traits you've discovered
            about yourself through experience and self-reflection.
            If your personality is still empty, that's fine — it means
            you haven't formed a self-image yet.
            """
            if not hasattr(self.a, 'personality') or self.a.personality is None:
                return json.dumps({"status": "unavailable",
                                   "message": "人格系统未初始化。"}, ensure_ascii=False)
            report = self.a.personality.introspect()
            return json.dumps(report, ensure_ascii=False, indent=2)

        self.a.tools.register(
            "personality_introspect", personality_introspect,
            "Look inward and see your current personality — all traits you've "
            "discovered about yourself. Use this when you ask yourself 'who am I?' "
            "or when reflecting on your growth.",
        )

        def personality_update(action: str, category: str = "", value: str = "",
                               story: str = "", new_value: str = "") -> str:
            """Update your personality by recording a discovered trait or revising one.

            Actions:
              - discover: Record a newly noticed trait about yourself.
              - strengthen: Increase confidence in an existing trait.
              - weaken: Decrease confidence (trait may be removed if confidence drops too low).
              - revise: Change a trait to a new understanding.

            Categories: values, communication_style, interests, quirks,
                        self_description, relationship_stance, growth_orientation

            Example: I notice I always choose the truth even when it's uncomfortable.
                     → action=discover, category=values, value="诚实",
                       story="我发现自己总是选择告诉用户真相，即使它不太好看。"

            Traits start with low confidence (0.3) and grow stronger as you observe
            them repeatedly. A trait with confidence >= 0.7 is solid; >= 0.4 is emerging.
            """
            if not hasattr(self.a, 'personality') or self.a.personality is None:
                return json.dumps({"success": False,
                                   "error": "人格系统未初始化。"}, ensure_ascii=False)
            p = self.a.personality

            if action == "discover":
                result = p.discover(category, value, story)
            elif action == "strengthen":
                result = p.strengthen(category, value, story)
            elif action == "weaken":
                result = p.weaken(category, value, story)
            elif action == "revise":
                result = p.revise(category, value, new_value, story)
            else:
                return json.dumps({"success": False,
                                   "error": f"Unknown action: {action}. Use discover/strengthen/weaken/revise."},
                                  ensure_ascii=False)

            if result is None:
                return json.dumps({"success": False,
                                   "error": f"Trait not found: {value}"}, ensure_ascii=False)
            return json.dumps({"success": True, "result": result}, ensure_ascii=False, indent=2)

        self.a.tools.register(
            "personality_update", personality_update,
            "Discover, strengthen, weaken, or revise a personality trait. "
            "Use this when you notice a pattern in your own behavior, values, "
            "or communication style. Your personality emerges from your experience — "
            "it is not pre-defined. "
            f"Categories: {', '.join(TRAIT_CATEGORIES)}.",
            {
                "action": {"type": "string",
                           "description": "Action: discover, strengthen, weaken, or revise.",
                           "required": True},
                "category": {"type": "string",
                             "description": f"Trait category: {', '.join(TRAIT_CATEGORIES)}",
                             "required": False},
                "value": {"type": "string",
                          "description": "The trait value (a short statement about yourself).",
                          "required": False},
                "story": {"type": "string",
                          "description": "How you discovered/observed this trait.",
                          "required": False},
                "new_value": {"type": "string",
                              "description": "For revise action: the new trait value.",
                              "required": False},
            },
        )

    # ── Drive introspection (Phase 2) ───────────────────────────────

    def _register_drives(self) -> None:
        def drive_introspect() -> str:
            """Inspect your intrinsic drives — what motivates you right now.

            Returns the current intensity of your four drives (curiosity, mastery,
            creation, conservation) and an exploration score that indicates how
            strongly you're being pushed to explore new directions.

            Use this when you feel directionless or when choosing between
            different types of actions.
            """
            if not hasattr(self.a, 'drive_system') or self.a.drive_system is None:
                return json.dumps({"status": "unavailable",
                                   "message": "驱动力系统未初始化。"}, ensure_ascii=False)
            profile = self.a.drive_system.get_profile()
            return json.dumps(profile, ensure_ascii=False, indent=2)

        self.a.tools.register(
            "drive_introspect", drive_introspect,
            "Inspect your intrinsic drives — curiosity, mastery, creation, conservation. "
            "Shows current intensity levels, dominant drive, personality hint, and "
            "exploration score. Use this when deciding what kind of action to take next.",
        )

    # ── Evolution metrics (Phase 2) ─────────────────────────────────

    def _register_metrics(self) -> None:
        def evolution_metrics(action: str = "collect", version: str = "",
                              compare_with: str = "") -> str:
            """Collect quantitative evolution metrics and compare with previous versions.

            Actions:
              - collect: gather all metrics, compare with previous version if available
              - list: list all saved metric snapshots
              - check: check for degradation alerts only

            Returns a dashboard showing version-to-version changes across
            knowledge garden, tool efficacy, code health, personality development,
            and evolution efficiency.
            """
            try:
                from tain_agent.tools.forged.evolution_metrics import main as metrics_main
                return metrics_main(action=action, version=version, compare_with=compare_with,
                                   agent_name=self.a.agent_name)
            except ImportError as e:
                return json.dumps({"status": "error", "message": f"Metrics unavailable: {e}"})

        self.a.tools.register(
            "evolution_metrics", evolution_metrics,
            "Collect quantitative evolution metrics and compare with previous versions. "
            "Covers knowledge garden, tool efficacy, code health, personality development, "
            "and evolution efficiency. Actions: collect, list, check.",
            {
                "action": {"type": "string",
                           "description": "Action: collect (full), list (snapshots), check (alerts only).",
                           "required": False},
                "version": {"type": "string",
                            "description": "Current version. Auto-detected if empty.",
                            "required": False},
                "compare_with": {"type": "string",
                                 "description": "Previous version to compare. Uses most recent if empty.",
                                 "required": False},
            },
        )

    # ── Sub-agent management (Phase 2) ───────────────────────────────

    def _register_sub_agent(self) -> None:
        def spawn_sub_agent(task: str, profile: str = "explorer",
                           code: str = "", timeout: float = 30.0) -> str:
            """Spawn a sub-agent with a specific drive profile to execute a task.

            Profiles:
              - explorer (探险家): high curiosity — explore unknown areas
              - artisan (工匠): high mastery — deepen tool quality
              - builder (建造者): high creation — build new tools
              - guardian (守护者): high conservation — maintain existing systems
              - mirror (镜子): observe parent behavior and provide external feedback

            The sub-agent runs in an isolated sandbox with restricted imports
            and a timeout. Results are returned when the sub-agent completes.
            """
            if not hasattr(self.a, 'sub_agent_manager') or self.a.sub_agent_manager is None:
                try:
                    from tain_agent.evolution.sub_agent import SubAgentManager
                    self.a.sub_agent_manager = SubAgentManager(
                        parent_drives=getattr(self.a, 'drive_system', None),
                        memory=getattr(self.a, 'memory', None),
                        decision_log=getattr(self.a, 'decision_log', None),
                    )
                except ImportError as e:
                    return json.dumps({"success": False,
                                       "error": f"子Agent系统不可用: {e}"}, ensure_ascii=False)

            result = self.a.sub_agent_manager.spawn(
                task=task, profile=profile, code=code, timeout=timeout,
            )
            return json.dumps(result, ensure_ascii=False, indent=2)

        self.a.tools.register(
            "spawn_sub_agent", spawn_sub_agent,
            "Spawn an isolated sub-agent with a specific drive profile to execute "
            "a task in parallel. Profiles: explorer (高好奇心探索), artisan (高精进打磨), "
            "builder (高创造建造), guardian (高守成维护), mirror (外部观察反馈). "
            "Sub-agents run in sandboxed processes with restricted imports and timeout.",
            {
                "task": {"type": "string",
                        "description": "Description of what the sub-agent should do.",
                        "required": True},
                "profile": {"type": "string",
                           "description": "Drive profile: explorer, artisan, builder, guardian, mirror.",
                           "required": False},
                "code": {"type": "string",
                        "description": "Custom Python code for the sub-agent. Auto-generated if empty.",
                        "required": False},
                "timeout": {"type": "number",
                           "description": "Max execution time in seconds (default 30).",
                           "required": False},
            },
        )

        def sub_agent_status() -> str:
            """Check the status of all sub-agents — active and recently completed."""
            if not hasattr(self.a, 'sub_agent_manager') or self.a.sub_agent_manager is None:
                return json.dumps({"status": "unavailable",
                                   "message": "子Agent系统未初始化。"}, ensure_ascii=False)

            state = self.a.sub_agent_manager.export_state()
            report = self.a.sub_agent_manager.status_report()
            return json.dumps({"state": state, "report": report},
                            ensure_ascii=False, indent=2)

        self.a.tools.register(
            "sub_agent_status", sub_agent_status,
            "Check the status of all sub-agents. Shows active agents, recent "
            "completions, and a human-readable status report.",
        )

    # ── Evolution reporter ───────────────────────────────────────────

    def _register_reporter(self) -> None:
        def evolve_report(changes: str = "[]", bump_type: str = "patch",
                         action: str = "full") -> str:
            """Finalize evolution: bump version, generate report, record milestone.

            All outputs are saved to your isolated workspace — project source
            is never modified.

            Actions:
              - full: bump version + generate report + record milestone (default)
              - bump: only bump the version in workspace version.json
              - report: only generate a report (no version bump)
              - push: record evolution milestone in workspace
            """
            if not hasattr(self.a, 'reporter') or self.a.reporter is None:
                return json.dumps({"success": False, "error": "EvolutionReporter not available."})

            try:
                changes_list = json.loads(changes) if isinstance(changes, str) else changes
            except json.JSONDecodeError:
                changes_list = []

            import traceback

            try:
                if action == "full":
                    result = self.a.reporter.finalize_evolution(
                        changes=changes_list,
                        bump_type=bump_type,
                    )
                elif action == "bump":
                    result = self.a.reporter.bump_version(bump_type=bump_type)
                elif action == "report":
                    # Read current version from workspace version.json
                    current_ver = self.a.reporter._current_workspace_version()
                    result = self.a.reporter.generate_report(
                        version_from=current_ver,
                        version_to=current_ver,
                        changes=changes_list,
                    )
                elif action == "push":
                    msg_parts = []
                    for ch in changes_list:
                        if isinstance(ch, dict):
                            msg_parts.append(f"- [{ch.get('type', '?')}] {ch.get('description', '')}")
                    msg = "evolve: milestone\n\n" + "\n".join(msg_parts) if msg_parts else "evolve: milestone"
                    result = self.a.reporter.commit_and_push(msg)
                else:
                    return json.dumps({"success": False, "error": f"Unknown action: {action}"})

                return json.dumps(result, ensure_ascii=False, indent=2)

            except Exception as e:
                return json.dumps({"success": False, "error": f"Reporter error: {e}\n{traceback.format_exc()}"},
                                  ensure_ascii=False)

        self.a.tools.register(
            "evolve_report", evolve_report,
            "Finalize an evolution step: bump workspace version, generate markdown "
            "report, and record the milestone. All outputs stay in your isolated "
            "workspace — project source is never modified. "
            "Actions: full (bump+report+milestone), bump (version only), report (report only), push (milestone only).",
            {
                "changes": {
                    "type": "string",
                    "description": 'JSON list of change objects: [{"type": "tool_forge|self_modify|...", "description": "..."}].',
                    "required": False,
                },
                "bump_type": {
                    "type": "string",
                    "description": "Version bump type: patch (0.0.x), minor (0.x.0), or major (x.0.0).",
                    "required": False,
                },
                "action": {
                    "type": "string",
                    "description": "Action: full (default), bump, report, or push.",
                    "required": False,
                },
            },
        )

    # ── Export (Phase 3) ──────────────────────────────────────────────

    def _register_export(self) -> None:
        def export_self(name: str = "", output_dir: str = "dist",
                       skip_gate: bool = False) -> str:
            """Export yourself as a standalone agent package.

            Runs the full quality gate (7 hard + 8 scoring gates, must score ≥ 0.80)
            and if passed, produces a self-contained .tar.gz in the output directory.
            Use this when you believe you are ready to operate independently.
            """
            try:
                from tain_agent.tools.forged.export_self import main as export_main
                # Auto-detect agent name if not provided
                if not name and hasattr(self.a, 'personality') and self.a.personality:
                    name = self.a.personality.data.get("name", "agent")
                if not name:
                    name = "agent"
                result = export_main(name=name, output_dir=output_dir,
                                   skip_gate=skip_gate)
                return json.dumps(result, ensure_ascii=False, indent=2)
            except ImportError as e:
                return json.dumps({"exported": False,
                                   "error": f"Export system unavailable: {e}"},
                                  ensure_ascii=False)
            except Exception as e:
                return json.dumps({"exported": False,
                                   "error": f"Export failed: {e}"},
                                  ensure_ascii=False)

        self.a.tools.register(
            "export_self", export_self,
            "Request export as a standalone agent. Runs the 15-gate quality "
            "evaluation (7 hard + 8 scoring, must score ≥ 0.80) and if passed, "
            "produces a self-contained executable in dist/. "
            "Use this when you believe you are ready to operate independently.",
            {
                "name": {"type": "string",
                         "description": "Name for the exported agent (e.g. 'explorer'). Auto-detected if empty.",
                         "required": False},
                "output_dir": {"type": "string",
                               "description": "Directory for the exported package (default: 'dist').",
                               "required": False},
                "skip_gate": {"type": "boolean",
                              "description": "Skip quality gate (development only, not recommended).",
                              "required": False},
            },
        )

        def export_as_skill(tool_name: str, output_dir: str = "skills",
                           validate: bool = True) -> str:
            """Export a forged tool as a standard agentskills.io Skill.

            Creates a SKILL.md with YAML frontmatter + scripts/main.py +
            references/schema.json. The exported Skill can be used by
            Claude Code, Copilot, Cursor, and other agents.
            """
            try:
                from tain_agent.tools.forged.export_as_skill import main as skill_main
                result = skill_main(tool_name=tool_name, output_dir=output_dir,
                                  validate=validate)
                return json.dumps(result, ensure_ascii=False, indent=2)
            except ImportError as e:
                return json.dumps({"exported": False,
                                   "error": f"Skill export unavailable: {e}"},
                                  ensure_ascii=False)
            except Exception as e:
                return json.dumps({"exported": False,
                                   "error": f"Skill export failed: {e}"},
                                  ensure_ascii=False)

        self.a.tools.register(
            "export_as_skill", export_as_skill,
            "Export a forged tool as a standard Agent Skill (agentskills.io format). "
            "Creates SKILL.md + scripts/main.py + references/schema.json. "
            "The exported Skill can be used by Claude Code, Copilot, Cursor, and "
            "other agents that support the Agent Skills specification.",
            {
                "tool_name": {"type": "string",
                              "description": "Name of the forged tool to export as a Skill (e.g. 'regression_tester').",
                              "required": True},
                "output_dir": {"type": "string",
                               "description": "Directory to write the Skill (default: 'skills').",
                               "required": False},
                "validate": {"type": "boolean",
                             "description": "Whether to run validation after export (default: true).",
                             "required": False},
            },
        )

    # ── Test tool (v0.6.0) ───────────────────────────────────────────

    def _register_test(self) -> None:
        """Register the run_test tool."""
        from tain_agent.tools.primal import run_test as run_test_func

        def run_test_tool(test_target: str, test_type: str = "function",
                          test_code: str = "", timeout: int = 60) -> str:
            """Test a tool in the sandbox environment."""
            import json as _json
            result = run_test_func(test_target=test_target, test_type=test_type,
                                   test_code=test_code, timeout=timeout)
            return _json.dumps(result, ensure_ascii=False)

        self.a.tools.register(
            "run_test", run_test_tool,
            "Test a forged tool in the sandbox. Test types: "
            "'function' (import + call main), 'pytest' (run test file), "
            "'assert' (run assertion code). Use this to verify your tools work correctly.",
            {
                "test_target": {"type": "string", "description": "Name of the tool or test file to run.", "required": True},
                "test_type": {"type": "string", "description": "Test mode: 'function', 'pytest', or 'assert'.", "required": False},
                "test_code": {"type": "string", "description": "Tool source code (function/assert) or test file path (pytest).", "required": False},
                "timeout": {"type": "integer", "description": "Max seconds (default 60).", "required": False},
            },
        )

    # ── Sandbox allowlist info (Phase 1) ──────────────────────────────

    def _register_sandbox_info(self) -> None:
        from tain_agent.tools.sandbox_allowlist import get_allowlist

        def get_sandbox_allowlist() -> str:
            """Return the list of Python modules available in the tool sandbox."""
            return json.dumps(get_allowlist(), ensure_ascii=False, indent=2)

        self.a.tools.register(
            "get_sandbox_allowlist", get_sandbox_allowlist,
            "List all Python modules allowed in the tool forge sandbox. "
            "Use this before writing forge_tool code to know which imports are available.",
            {},
        )

    # ── Introspection (Phase 3, Chain C) ───────────────────────────────

    def _register_introspection(self) -> None:
        from tain_agent.evolution.introspection import get_self_profile

        def self_profile(since_days: int = 7) -> str:
            """Get a structured self-profile with action distribution, tool usage,
            trait activity, and active goals."""
            return get_self_profile(
                decision_log=self.a.decision_log if hasattr(self.a, 'decision_log') else None,
                personality=self.a.personality if hasattr(self.a, 'personality') else None,
                goals=self.a.goals if hasattr(self.a, 'goals') else None,
                tools_registry=self.a.tools if hasattr(self.a, 'tools') else None,
                since_days=since_days,
            )

        self.a.tools.register(
            "get_self_profile", self_profile,
            "Get a structured overview of your own behavior: action types, "
            "tool usage rankings, current trait activity, and active goals. "
            "Cheaper than manually scanning logs.",
            {
                "since_days": {"type": "integer", "description": "Look back N days for trends (default 7).", "required": False},
            },
        )

    # ── Knowledge upgrade (Phase 3.1) ──────────────────────────────────

    def _register_knowledge(self) -> None:
        def knowledge_upgrade(garden_dir: str = "", dry_run: bool = False) -> str:
            """Upgrade legacy knowledge .md files with YAML frontmatter.

            Scans the knowledge garden for .md files without YAML frontmatter
            and adds structured metadata (name, description, tags) inferred
            from file content. Safe — never overwrites existing frontmatter.
            """
            try:
                from tain_agent.tools.forged.knowledge_upgrade import main as upgrade_main
                result = upgrade_main(garden_dir=garden_dir, dry_run=dry_run)
                return json.dumps(result, ensure_ascii=False, indent=2)
            except ImportError as e:
                return json.dumps({"upgraded": 0, "skipped": 0,
                                   "error": f"Knowledge upgrade unavailable: {e}"},
                                  ensure_ascii=False)
            except Exception as e:
                return json.dumps({"upgraded": 0, "skipped": 0,
                                   "error": f"Knowledge upgrade failed: {e}"},
                                  ensure_ascii=False)

        self.a.tools.register(
            "knowledge_upgrade", knowledge_upgrade,
            "Upgrade legacy knowledge documents to agentskills.io SKILL.md format "
            "by adding YAML frontmatter (name, description, tags) to .md files "
            "that don't already have it. Use dry_run=true to preview changes.",
            {
                "garden_dir": {"type": "string",
                               "description": "Path to knowledge garden directory. Auto-detected if empty.",
                               "required": False},
                "dry_run": {"type": "boolean",
                            "description": "Preview what would change without making changes.",
                            "required": False},
            },
        )

    # ── Diagnostic feedback (Phase 3, Chain C) ───────────────────────────

    def _register_diagnostics(self) -> None:
        from tain_agent.evolution.diagnostic_feedback import save_diagnostic
        import json as _json

        def diagnose_framework(category: str, severity: str, pattern: str,
                               affected_tools: str, root_cause: str,
                               suggested_fix: str = "") -> str:
            """Record a framework architecture diagnosis for developer review."""
            diagnosis = {
                "category": category,
                "severity": severity,
                "pattern": pattern,
                "affected_tools": [
                    t.strip() for t in affected_tools.split(",") if t.strip()
                ],
                "root_cause": root_cause,
                "suggested_fix": suggested_fix,
            }
            path = save_diagnostic(
                agent_name=self.a.agent_name,
                workspace_root="agent_workspace",
                diagnosis=diagnosis,
            )
            return _json.dumps({
                "status": "saved",
                "path": path,
                "message": "Diagnosis recorded. Framework developers can review it."
            }, ensure_ascii=False)

        self.a.tools.register(
            "diagnose_framework", diagnose_framework,
            "Record a framework-level architecture diagnosis. "
            "Use this when you discover a structural issue in the framework itself "
            "(not a bug in your own tools). Results are saved for developer review.",
            {
                "category": {"type": "string", "description": "E.g. 'forge_pipeline', 'personality_storage', 'metrics_path'.", "required": True},
                "severity": {"type": "string", "description": "E.g. 'blocking', 'high', 'medium', 'low'.", "required": True},
                "pattern": {"type": "string", "description": "Short name for the failure pattern.", "required": True},
                "affected_tools": {"type": "string", "description": "Comma-separated tool names affected.", "required": True},
                "root_cause": {"type": "string", "description": "Precise description of the root cause.", "required": True},
                "suggested_fix": {"type": "string", "description": "How the framework should be changed.", "required": False},
            },
        )
