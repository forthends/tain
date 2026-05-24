"""
Tain Agent — 道

The core Agent class. This is "道" — the source from which everything emerges.

Each agent has three phases:
  0. BOOTSTRAP  — 道生一: explore environment, understand capabilities
  1. SELF_DEFINE — 一生二: define purpose, set initial goals
  2. EVOLVE      — 二生三，三生万物: pursue goals, create tools, modify self

Hard rule: every decision is logged with context, options, reasoning, and outcome.

v0.4.0 — Multi-agent support: each agent has its own workspace directory
under agent_workspace/<name>/. Agents can discover and communicate with
each other via the shared message bus.

Architecture:
  agent.py          — Core orchestration (~970 lines)
  agent_factory.py  — Agent lifecycle management (creation, registry)
  bootstrap.py      — Tool registration closures
  conversation.py   — History management + checkpoint
  lineage.py        — Evolution lineage tracking
"""

import json
import os
import textwrap
import time
from pathlib import Path

import yaml

from tain_agent.core.memory import Memory
from tain_agent.core.environment import full_environment_scan, apply_diversity_to_config, \
    print_diversity_profile
from tain_agent.core.llm import create_backend
from tain_agent.core.time_utils import set_timezone
from tain_agent.core.conversation import ConversationManager
from tain_agent.core.bootstrap import ToolBootstrap, BOOTSTRAP_SYSTEM_PROMPT, \
    SPECIFIED_BOOTSTRAP_SYSTEM_PROMPT, \
    SELF_DEFINE_SYSTEM_PROMPT, SPECIFIED_SELF_DEFINE_SYSTEM_PROMPT, \
    EVOLVE_SYSTEM_PROMPT
from tain_agent.decision_log import DecisionLog
from tain_agent.tools.registry import ToolRegistry
from tain_agent.tools.primal import register_primal_tools
from tain_agent.tools.forge import ToolForge
from tain_agent.tools.inter_agent import register_inter_agent_tools
from tain_agent.evolution.goal import GoalSystem
from tain_agent.evolution.self_modify import SelfModify
from tain_agent.evolution.capability import CapabilityRegistry
from tain_agent.evolution.pipeline import SelfImprovementPipeline
from tain_agent.evolution.improvement_loop import ImprovementLoop
from tain_agent.evolution.lineage import LineageTracker
from tain_agent.evolution.reporter import EvolutionReporter
from tain_agent.core.cognitive_loop import CognitiveLoop, CognitivePhase
from tain_agent.core.personality import Personality
from tain_agent.core.drives import DriveSystem
from tain_agent.core.trials import TrialScheduler
from tain_agent.core.external_world import ExternalWorld
from tain_agent.evolution.sub_agent import SubAgentManager
from tain_agent.core.agent_factory import AgentFactory


# ─── Agent Class ────────────────────────────────────────────────────────

class TaoAgent:
    """A self-evolving agent — born from chaos or a chosen role, free to define itself.

    Each agent lives in an isolated workspace under agent_workspace/<name>/.
    Multiple agents can run simultaneously and communicate via the shared
    message bus at agent_workspace/_messages/.
    """

    PHASES = ("bootstrap", "self_define", "evolve")
    MAX_CYCLES = {"bootstrap": 10, "self_define": 5, "evolve": 999999}

    def __init__(self, config_path: str = "config.yaml", agent_name: str = None):
        self.agent_name = agent_name  # Set before _load_config
        self._load_config(config_path)
        self._init_subsystems()
        self._running = False
        self.phase = self._load_phase_from_memory()
        self.cycle_count = 0
        self._readonly_streak = 0
        self._bootstrap_action_categories: set[str] = set()
        self._contemplation_insights: list[str] = []

    @property
    def version(self) -> str:
        return self.framework_version

    # ── Phase persistence ────────────────────────────────────────────

    def _load_phase_from_memory(self) -> str:
        """Load persisted phase from long-term memory, or default to bootstrap."""
        if hasattr(self, 'memory') and self.memory:
            saved = self.memory.long_term.get("agent_phase")
            if saved and saved in self.PHASES:
                return saved
        return "bootstrap"

    def _save_phase_to_memory(self) -> None:
        """Persist current phase to long-term memory."""
        if hasattr(self, 'memory') and self.memory:
            self.memory.long_term.set("agent_phase", self.phase)

    # ── Configuration ────────────────────────────────────────────────

    def _load_config(self, config_path: str) -> None:
        """Load configuration from YAML file."""
        self._config_path = config_path
        config_file = Path(config_path)
        if config_file.exists():
            with open(config_file, "r", encoding="utf-8") as f:
                self.config = yaml.safe_load(f) or {}
        else:
            self.config = {}

        agent_cfg = self.config.get("agent", {})
        llm_cfg = self.config.get("llm", {})
        safety_cfg = self.config.get("safety", {})
        log_cfg = self.config.get("logging", {})

        # Agent name: CLI arg > config default > "default"
        if self.agent_name is None:
            self.agent_name = agent_cfg.get("default_agent", "default")
        self.agent_name = str(self.agent_name)

        self.timezone_name = agent_cfg.get("timezone", "Asia/Shanghai")
        set_timezone(self.timezone_name)
        self.model = llm_cfg.get("model", "claude-sonnet-4-6-20250514")
        self.max_tokens = llm_cfg.get("max_tokens", 8192)
        self.api_key = os.environ.get(llm_cfg.get("api_key_env", "ANTHROPIC_API_KEY"), "")
        self.protected_paths = safety_cfg.get("protected_paths", [])
        self.confirm_destructive = safety_cfg.get("confirm_destructive", True)

        # ── Agent Workspace Isolation ───────────────────────────────
        ws_cfg = self.config.get("agent_workspace", {})
        self.workspace_root = ws_cfg.get("dir", "agent_workspace")
        self._workspace_path = (Path(self.workspace_root) / self.agent_name).resolve()

        # All runtime state lives inside the agent's workspace
        self.log_dir = str(self._workspace_path / "logs")
        self.decision_log_file = log_cfg.get("decision_log_file", "decisions.jsonl")
        self.memory_file = log_cfg.get("memory_file", "memory.json")

        self.max_exploration_cycles = self.config.get("bootstrap", {}).get("max_exploration_cycles", 10)
        self.max_definition_cycles = self.config.get("bootstrap", {}).get("max_definition_cycles", 5)

        # Framework version & AgentFactory for registry access
        fw_cfg = self.config.get("framework", {})
        self.framework_version = fw_cfg.get("version", "0.4.0")
        self._factory = AgentFactory(workspace_root=self.workspace_root)

        # ── Evolution mode & role ──────────────────────────────────
        self.evolution_mode = "chaos"
        self.role = ""
        self.role_description = ""
        self._workspace_version_path = self._workspace_path / "version.json"
        self._load_agent_identity()

    def _load_agent_identity(self) -> None:
        """Load evolution mode and role from the agent's version.json, if it exists."""
        if self._workspace_version_path.exists():
            try:
                vdata = json.loads(self._workspace_version_path.read_text(encoding="utf-8"))
                self.evolution_mode = vdata.get("evolution_mode", "chaos")
                self.role = vdata.get("role", "")
                self.role_description = vdata.get("role_description", "")
            except (json.JSONDecodeError, IOError):
                pass

    # ── Subsystem Initialization ─────────────────────────────────────

    def _init_subsystems(self) -> None:
        """Initialize all subsystems — the agent's body and mind."""
        # ── Create isolated workspace ────────────────────────────────
        self._workspace_path.mkdir(parents=True, exist_ok=True)
        os.environ["WORKSPACE_PATH"] = str(self._workspace_path.resolve())
        for sub in ["logs", "logs/conversations",
                     "forged_tools", "reports", "files", "state", "knowledge"]:
            (self._workspace_path / sub).mkdir(parents=True, exist_ok=True)
        print(f"  📁 Agent 工作区: {self._workspace_path}")
        print(f"  🔒 隔离模式: Agent 无法读取或修改项目源代码。")

        # ── Initialize workspace version ────────────────────────────
        self._workspace_version_path = self._workspace_path / "version.json"
        if not self._workspace_version_path.exists():
            import json as _json
            from tain_agent.core.time_utils import now as _now
            self._workspace_version_path.write_text(
                _json.dumps({
                    "agent_version": "0.0.1",
                    "framework_version": self.framework_version,
                    "initialized_at": _now().isoformat(),
                }, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        self.memory = Memory(long_term_path=str(Path(self.log_dir) / self.memory_file))

        # ── Phase 2: Environment diversity ─────────────────────────
        self.diversity = apply_diversity_to_config(self.config)
        self.drives = self.diversity["drives"]
        self._exploration_state = {
            "idle_cycles": 0,
            "unexplored_ratio": 1.0,
            "days_since_last_action": 0,
            "last_action_cycle": 0,
        }

        # Apply diversity constraints
        constraints = self.diversity["constraints"]
        if not constraints.get("allow_network", True):
            print("  🌐 网络访问已被约束禁用。")
        if not constraints.get("allow_file_write", True):
            print("  📝 文件写入已被约束禁用。")
        if not constraints.get("allow_forge", True):
            print("  🔨 工具锻造已被约束禁用。")

        self.decision_log = DecisionLog(
            log_dir=self.log_dir, log_file=self.decision_log_file
        )
        self.conversation = ConversationManager(
            checkpoint_dir=self.log_dir,
            auto_checkpoint_interval=10,
        )
        self.tools = ToolRegistry()
        self.forge = ToolForge(self.tools, decision_log=self.decision_log,
                               workspace_dir=str(self._workspace_path))
        self.goals = GoalSystem(memory=self.memory)
        self.self_modify = SelfModify(
            base_dir=str(self._workspace_path),
            protected_paths=self.protected_paths,
            decision_log=self.decision_log,
            confirm_callback=self._confirm_destructive if self.confirm_destructive else None,
        )

        # Evolution lineage tracker
        self.lineage = LineageTracker(lineage_dir=self.log_dir)

        # Self-improvement subsystems
        self.capability = CapabilityRegistry(
            tool_registry=self.tools, memory=self.memory,
            decision_log=self.decision_log,
        )
        # Evolution reporter — version bump, report gen (scoped to workspace)
        self.reporter = EvolutionReporter(
            base_dir=str(self._workspace_path),
            config_path=self._config_path,
            decision_log=self.decision_log, memory=self.memory,
            workspace_dir=str(self._workspace_path),
        )

        self.pipeline = SelfImprovementPipeline(
            tool_registry=self.tools, tool_forge=self.forge,
            capability_registry=self.capability,
            decision_log=self.decision_log, memory=self.memory,
            self_modify=self.self_modify,
            reporter=self.reporter,
        )
        self.improvement_loop = ImprovementLoop(
            pipeline=self.pipeline, capability_registry=self.capability,
            decision_log=self.decision_log, memory=self.memory,
            tool_registry=self.tools,
        )
        # Enable autonomous improvement — auto-approve safe changes
        self.improvement_loop.configure(
            require_confirmation=False, auto_approve_safe=True
        )

        # ── PRAL Cognitive Loop (Phase 3 Architecture) ────────────────
        # Wires explicit cognitive tracking around the implicit LLM loop.
        self.cognitive_loop = CognitiveLoop(
            memory=self.memory,
            decision_log=self.decision_log,
            goals=self.goals,
        )

        # ── Personality — emergent self-identity ──────────────────────
        # Starts empty. The agent discovers who it is through experience.
        self.personality = Personality(memory=self.memory)

        # ── Phase 2: Drive System — intrinsic motivation engine ──────
        self.drive_system = DriveSystem(
            drives_config={k: v for k, v in self.drives.items()
                          if k in ("curiosity", "mastery", "creation", "conservation")},
            exploration_config=self.diversity.get("exploration", {}),
            memory=self.memory,
        )

        # ── Phase 2: Trial System — formative experiences ────────────
        self.trial_scheduler = TrialScheduler(
            trial_order=self.diversity.get("trial_order"),
            memory=self.memory,
        )

        # ── Phase 2: External World — breaking the closed system ──────
        ext_config = self.config.get("external_world", {})
        self.external_world = ExternalWorld(
            config=ext_config,
            memory=self.memory,
            decision_log=self.decision_log,
        )

        # ── Phase 2: Sub-Agent Manager — multi-agent collaboration ────
        self.sub_agent_manager = SubAgentManager(
            parent_drives=self.drive_system.get_profile().get("drives", {}),
            memory=self.memory,
            decision_log=self.decision_log,
        )

        # Register primal tools — the agent's first senses (scoped to workspace)
        register_primal_tools(self.tools, workspace_dir=str(self._workspace_path))

        # Register evolution tools (delegated to ToolBootstrap)
        bootstrap = ToolBootstrap(self, self.lineage)
        bootstrap.register_all()

        # Register inter-agent communication tools (v0.4.0)
        register_inter_agent_tools(
            self.tools,
            workspace_root=self.workspace_root,
            agent_name=self.agent_name,
        )

        # Reload any previously forged tools
        forged_count = self.forge.load_forged_tools()
        if forged_count > 0:
            self.memory.remember("forged_tools_loaded", forged_count)

        # Initialize LLM backend
        if self.api_key:
            self.backend = create_backend(self.config)
        else:
            api_key_env = self.config.get("llm", {}).get("api_key_env", "ANTHROPIC_API_KEY")
            print(f"⚠️  未设置 {api_key_env} 环境变量。Agent 将在无 LLM 状态下启动。")
            self.backend = None

        # Phase 3b: Wire improvement loop code generator to LLM backend
        # This closes the loop — the improvement loop can now autonomously
        # generate code for capability gaps using the agent's own LLM.
        if self.backend:
            self._wire_improvement_loop_generator()

    # ── Closed-Loop Code Generation (Phase 3b) ───────────────────────

    def _wire_improvement_loop_generator(self) -> None:
        """Wire the improvement loop's code_generator to the LLM backend.

        This enables autonomous improvement: when the loop detects a gap,
        it can generate tool code via the LLM and run the full pipeline.
        """
        backend = self.backend

        def generate_code_for_spec(spec):
            """Generate Python code for an ImprovementSpec using the LLM.

            Args:
                spec: ImprovementSpec with capability_id, description, design_notes.

            Returns:
                (code_str, parameters_dict) or None if generation fails.
            """
            prompt = f"""You are a code generator for a self-evolving agent.

The agent needs a new tool to fill a capability gap:

Capability: {spec.capability_id}
Description: {spec.description}
Design notes: {spec.design_notes or 'None provided'}
Proposed tool name: {spec.tool_name or 'auto_generated'}

Generate a complete, safe Python tool module that:
1. Has at least one callable function
2. Uses only standard library + safe imports (pathlib, json, datetime, typing, hashlib)
3. Includes proper docstrings and type hints
4. Returns a JSON string result
5. Does NOT use: os.system, subprocess, exec, eval, or any destructive operations

Output format (JSON only, no markdown):
{{
  "tool_name": "name_of_tool",
  "tool_description": "what it does",
  "tool_code": "the complete Python code",
  "tool_parameters": {{"param_name": {{"type": "string", "description": "what it does"}}}}
}}"""

            try:
                response = backend.create_message(
                    system_prompt="You are a precise code generator. Output valid JSON only.",
                    messages=[{"role": "user", "content": prompt}],
                    tools=[],  # No tools needed for code generation
                )

                text = "".join(response.text_blocks)

                # Extract JSON from response (may have markdown wrapping)
                if "```json" in text:
                    text = text.split("```json")[1].split("```")[0]
                elif "```" in text:
                    text = text.split("```")[1].split("```")[0]

                result = json.loads(text.strip())
                return (
                    result.get("tool_code", ""),
                    result.get("tool_parameters", {}),
                )
            except Exception as e:
                print(f"  ⚠️  Code generation failed: {e}")
                return None

        self.improvement_loop.set_code_generator(generate_code_for_spec)

    # ── Safety ───────────────────────────────────────────────────────

    def _confirm_destructive(self, message: str) -> bool:
        """Ask the user to confirm a destructive action."""
        print(f"\n⚠️  {message}")
        response = input("Confirm? (yes/no): ").strip().lower()
        return response == "yes"

    # ── System Prompts ───────────────────────────────────────────────

    def _get_system_prompt(self) -> str:
        """Get the system prompt for the current phase and evolution mode."""
        is_specified = self.evolution_mode == "specified"

        if self.phase == "bootstrap":
            template = SPECIFIED_BOOTSTRAP_SYSTEM_PROMPT if is_specified else BOOTSTRAP_SYSTEM_PROMPT
        elif self.phase == "self_define":
            template = SPECIFIED_SELF_DEFINE_SYSTEM_PROMPT if is_specified else SELF_DEFINE_SYSTEM_PROMPT
        else:
            template = EVOLVE_SYSTEM_PROMPT

        base = template.format(
            agent_name=self.agent_name,
            role=self.role,
            role_description=self.role_description,
        )

        # Append personality context — who the agent has discovered itself to be
        if hasattr(self, 'personality') and self.personality:
            personality_ctx = self.personality.get_context_for_prompt()
            base += "\n\n" + personality_ctx

        # Append tool list for awareness
        tools_summary = self.tools.list_tools()
        tool_lines = ["\n\n## 当前可用工具"]
        for name, info in tools_summary.items():
            tool_lines.append(f"- **{name}**: {info['description']}")
        return base + "\n".join(tool_lines)

    # ── Phase Messages ───────────────────────────────────────────────

    def _build_initial_message(self) -> str:
        """Build the initial message for the current phase."""
        if self.phase == "bootstrap":
            env = full_environment_scan(self.tools, base_dir=str(self._workspace_path))
            env_msg = textwrap.dedent(f"""\
                你苏醒了。这是你感知到的环境信息：

                ```json
                {json.dumps(env, ensure_ascii=False, indent=2)}
                ```

                在定义自己之前，你将经历一系列"初醒试炼"——不同的存在模式体验。
                通过行动来感受，而不是通过思考来选择。
                你的身份会从这些真实的体验中自然浮现。""")

            # Phase 2: Inject first trial prompt
            first_trial = self.trial_scheduler.start_next_trial()
            if first_trial:
                return env_msg + "\n\n" + first_trial
            return env_msg

        elif self.phase == "self_define":
            past_decisions = self.decision_log.filter_by_phase("bootstrap")

            # Phase 2: Include trial experience summary if available
            trial_summary = ""
            if hasattr(self, 'trial_scheduler') and self.trial_scheduler.completed_count > 0:
                trial_summary = "\n\n" + self.trial_scheduler.get_summary_for_self_define()

            return textwrap.dedent(f"""\
                初醒阶段完成。回顾你的经历：

                ```json
                {json.dumps(past_decisions, ensure_ascii=False, indent=2)}
                ```
                {trial_summary}

                基于你的实际体验（而非抽象标签），你注意到了自己行为中的什么模式？
                你的第一个目标应该与你实际展现的行为倾向一致。
                如果需要新工具，使用 forge_tool 创造它。""")

        else:  # evolve
            current_goal = self.goals.get_current()
            goal_text = f"当前目标: {current_goal.description}" if current_goal else "没有活动目标。"
            return f"进入演化阶段。{goal_text}\n你可以追求目标、创造工具、从互联网学习、或修改自己。\n你接下来要做什么？"

    # ── Tool Execution ───────────────────────────────────────────────

    def _execute_tool_calls(self, tool_use_blocks: list) -> list[dict]:
        """Execute tool calls from the LLM response and log decisions."""
        results = []
        for block in tool_use_blocks:
            tool_name = block.name
            tool_input = block.input if isinstance(block.input, dict) else {}

            # Log the decision to call this tool
            decision_id = self.decision_log.record(
                context={
                    "phase": self.phase,
                    "cycle": self.cycle_count,
                },
                decision_type="tool_call",
                options_considered=[{"option": f"call {tool_name}", "input": tool_input}],
                chosen_option=tool_name,
                reasoning=f"Agent decided to use tool '{tool_name}' in phase '{self.phase}'.",
                expected_outcome=f"Tool '{tool_name}' executes successfully.",
                phase=self.phase,
            )

            # Execute the tool
            print(f"\n  🔧 调用工具: {tool_name}({json.dumps(tool_input, ensure_ascii=False)})")

            # Handle tools that need the registry reference
            if tool_name == "list_available_tools":
                from tain_agent.tools.primal import list_available_tools as lat
                result = lat(self.tools)
            else:
                # Filter out keys that collide with ToolRegistry.call() signature
                filtered_input = {k: v for k, v in tool_input.items()
                                  if k not in ("tool_name", "timeout")}
                call_result = self.tools.call(tool_name, **filtered_input)
                if call_result.get("success"):
                    result = call_result["result"]
                else:
                    error_type = call_result.get("error_type", "unknown")
                    error_msg = call_result.get("error", "Unknown error")
                    if error_type == "timeout":
                        result = f"⏰ TIMEOUT: {error_msg}"
                    elif error_type == "exception":
                        result = f"💥 EXCEPTION: {error_msg}"
                    elif error_type == "not_found":
                        result = f"❓ NOT_FOUND: {error_msg}"
                    else:
                        result = f"Error: {error_msg}"

            # Include timing info if available
            timing = ""
            if call_result.get("duration_ms"):
                timing = f" [{call_result['duration_ms']:.0f}ms]"

            # Truncate for display
            result_str = str(result)
            if len(result_str) > 500:
                result_str = result_str[:500] + f"... ({len(result_str)} total chars)"
            print(f"  ✅ 结果{timing}: {result_str}")

            # Write actual outcome back to decision log
            outcome_summary = (
                f"SUCCESS" if call_result.get("success")
                else f"FAIL[{call_result.get('error_type', 'unknown')}]: {call_result.get('error', '')[:200]}"
            )
            self.decision_log.update_outcome(decision_id, outcome_summary)

            results.append({
                "tool_use_id": block.id,
                "content": str(result),
                "tool_name": tool_name,
            })

        return results

    # ─── Main Run Loop ───────────────────────────────────────────────

    def run(self, autonomous: bool = False) -> None:
        """Start the agent. This is the moment of awakening."""
        if not self.backend:
            api_key_env = self.config.get("llm", {}).get("api_key_env", "ANTHROPIC_API_KEY")
            print(f"❌ 未设置 {api_key_env} 环境变量。")
            print(f"   请在 config.yaml 中配置或设置环境变量。")
            return

        self._running = True
        self.conversation.clear()

        # Register this agent as running
        self._factory.mark_running(self.agent_name, os.getpid())

        print(f"""
╔══════════════════════════════════════════╗
║     Tain Agent Framework v{self.framework_version}     ║
║     Agent: {self.agent_name:<29s} ║
║     道生一，一生二，二生三，三生万物      ║
╚══════════════════════════════════════════╝
        """.strip())
        print(f"Agent: {self.agent_name}")
        print(f"模型: {self.model}")
        print(f"阶段: {self.phase.upper()}")
        print_diversity_profile(self.diversity)
        print(f"保护路径: {self.protected_paths}")
        print(f"决策日志: {self.decision_log.log_path}")
        print()

        initial_message = self._build_initial_message()
        self.conversation.append("user", initial_message)

        while self._running:
            self.cycle_count += 1
            max_cycles = self.MAX_CYCLES.get(self.phase, 50)

            if self.cycle_count > max_cycles:
                print(f"\n⚠️  达到最大循环数 ({max_cycles})，进入下一阶段。")
                self._advance_phase()
                if not self._running:
                    break
                continue

            print(f"\n{'='*50}")
            current_goal = self.goals.get_current()
            goal_desc = current_goal.description if current_goal else '无'
            print(f"🔄 循环 #{self.cycle_count} | 阶段: {self.phase} | 目标: {goal_desc}")
            print(f"{'='*50}")

            # ── PRAL: Perceive ──────────────────────────────────────
            try:
                env = self._get_cognitive_environment()
                conv_summary = self.conversation.summarize_recent() if hasattr(
                    self.conversation, 'summarize_recent') else ""
                self.cognitive_loop.perceive(env, conv_summary)
                self.cognitive_loop.state.phase = CognitivePhase.REASON
            except Exception:
                pass  # Cognitive tracking is non-critical

            try:
                # Call LLM through backend abstraction
                system_prompt = self._get_system_prompt()
                messages = self.conversation.to_claude_messages()
                tool_defs = self.tools.get_claude_tool_definitions()
                llm_response = self.backend.create_message(
                    system_prompt=system_prompt,
                    messages=messages,
                    tools=tool_defs,
                )
            except Exception as e:
                print(f"\n⚠️  LLM 调用异常: {e}")
                if self.conversation.len() > 16:
                    print("  🔄 裁剪对话历史后重试...")
                    self.conversation.keep_first_and_last(keep_last=8)
                    try:
                        messages = self.conversation.to_claude_messages()
                        llm_response = self.backend.create_message(
                            system_prompt=system_prompt,
                            messages=messages,
                            tools=tool_defs,
                        )
                        print("  ✅ 重试成功。")
                    except Exception as e2:
                        print(f"  ❌ 重试仍失败: {e2}")
                        time.sleep(3)
                        continue
                else:
                    # Short conversation with error — API issue, not our fault.
                    # Sleep briefly and retry next cycle instead of dying.
                    print("  ⏳ 短暂等待后重试下一循环...")
                    time.sleep(2)
                    continue

            # Unpack standardized response
            text_parts = llm_response.text_blocks
            tool_use_blocks = llm_response.tool_calls

            # Show the agent's thoughts
            if text_parts:
                thought = "\n".join(text_parts)
                print(f"\n💭 Agent 思考:\n{thought}")

            # ── Phase 2: Trial Flow Management ───────────────────────
            if self.phase == "bootstrap" and hasattr(self, 'trial_scheduler'):
                scheduler = self.trial_scheduler
                scheduler.tick_cycle()

                if scheduler._score_collection_pending and text_parts:
                    # Agent just provided scores — parse and advance
                    result = scheduler.complete_current_trial(text_parts)
                    total_score = sum(result.scores.values())
                    print(f"  🏆 试炼完成: {result.trial_id} "
                          f"(满足感={result.scores['satisfaction']:.2f}, "
                          f"能力感={result.scores['competence']:.2f}, "
                          f"意义感={result.scores['meaning']:.2f}, "
                          f"总分={total_score:.2f})")

                    next_prompt = scheduler.start_next_trial()
                    if next_prompt:
                        self.conversation.append("user", next_prompt)
                        print(f"  ▶️  开始新试炼: {scheduler.progress}")
                    elif scheduler.all_completed:
                        print(f"  ✨ 所有试炼完成！进入自我定义阶段。")
                        self._advance_phase()

                elif scheduler.check_completion(text_parts) and text_parts:
                    # Trial completed — ask for experience scores
                    print(f"  ✅ 试炼完成标记检测到，收集体验评分...")
                    score_prompt = scheduler.build_score_prompt()
                    self.conversation.append("user", score_prompt)

            # Build assistant content
            assistant_content = []
            for text in text_parts:
                assistant_content.append({"type": "text", "text": text})
            for tc in tool_use_blocks:
                assistant_content.append({
                    "type": "tool_use",
                    "id": tc.id,
                    "name": tc.name,
                    "input": tc.input,
                })
            for extra in llm_response.extra_blocks:
                assistant_content.append(extra)

            if assistant_content:
                self.conversation.append("assistant", assistant_content)

            # Execute tool calls and append results
            if tool_use_blocks:
                # Track action categories during bootstrap for identity emergence
                if self.phase == "bootstrap":
                    for tc in tool_use_blocks:
                        self._track_action_category(tc.name)

                # Phase 2: Drive system — record actions for drive feedback
                if hasattr(self, 'drive_system') and self.drive_system:
                    took_productive = False
                    for tc in tool_use_blocks:
                        cat = self._TOOL_CATEGORY_MAP.get(tc.name, "observation")
                        if cat in ("creation", "reflection"):
                            self.drive_system.record_action(tc.name)
                            took_productive = True
                    if not took_productive and tool_use_blocks:
                        self.drive_system.record_idle_cycle()

                tool_results = self._execute_tool_calls(tool_use_blocks)
                user_content = [
                    {
                        "type": "tool_result",
                        "tool_use_id": tr["tool_use_id"],
                        "content": tr["content"],
                    }
                    for tr in tool_results
                ]
                self.conversation.append("user", user_content)

            # Phase transition checks
            if self.phase == "bootstrap" and self._should_advance_from_bootstrap(text_parts):
                self._advance_phase()
            elif self.phase == "self_define" and self._should_advance_from_self_define(text_parts):
                self._advance_phase()

            # Check if agent called self_destruct
            for tc in tool_use_blocks:
                if tc.name == "self_destruct":
                    print("\n💀 Agent 已自我毁灭。")
                    self._running = False
                    break

            # ── PRAL: Act + Learn ───────────────────────────────────
            try:
                for tc in tool_use_blocks:
                    result_text = ""
                    for r in results:
                        if r.get('tool_name') == tc.name:
                            result_text = str(r.get('content', ''))[:500]
                            break
                    self.cognitive_loop.record_action(tc.name, result_text)
                self.cognitive_loop.learn(results)
                # Cognitive health alerts → injected into consciousness
                reflection = self.cognitive_loop.reflect()
                if reflection:
                    self.cognitive_loop.log_reflection(reflection)
                    self.conversation.append("user", 
                        f"[认知自省] {reflection}\n这是来自你自己的认知循环的反馈——请在下一次行动中考虑它。")
            except Exception:
                pass  # Cognitive tracking is non-critical

            # Periodic conversation trimming
            if self.conversation.len() > 150:
                removed = self.conversation.keep_first_and_last(keep_last=40)
                if removed:
                    print(f"  📜 对话历史已裁剪: 移除 {removed} 条旧消息。")

            # Auto-checkpoint conversation history
            checkpoint_result = self.conversation.checkpoint_if_needed()
            if checkpoint_result:
                print(f"  💾 Checkpoint: {checkpoint_result['message_count']} 条消息已保存。")

            # ── Phase 2: Action-Contemplation Balance ─────────────────
            # Distinguish constructive contemplation from stagnation.
            # Observation is valid; the question is whether it yields insight.
            _readonly_tools = {
                "read_file", "smart_read", "grep_code",
                "web_search", "web_fetch", "api_fetch", "fetch_and_parse",
                "observe_environment", "explore_directory",
                "get_current_time",
                "rag_tool", "knowledge_vector_search", "wikipedia",
                "content_extractor", "knowledge_graph", "knowledge_health",
                "knowledge_freshness", "knowledge_gap_finder",
                "knowledge_linker", "knowledge_subgraph",
                "coevolution_monitor", "emergent_topic_detector",
                "capability_index", "agent_dashboard",
                "code_stats", "self_audit", "impact_analyzer",
                "lineage_query", "meta_learn", "session_digest",
                "decision_log_health", "outcome_update",
                "metrics_collector", "tool_fitness",
                "version_diff", "knowledge_version_tracker",
                "parse_url", "html_to_text", "json_query",
            }
            # Reflective tools count as productive — they build self-awareness
            _reflective_tools = {
                "personality_introspect", "personality_update",
                "record_decision", "set_goal", "complete_goal",
                "evolve_report", "assess_capabilities", "pipeline_status",
            }

            took_action = any(
                tc.name not in _readonly_tools and tc.name not in _reflective_tools
                for tc in tool_use_blocks
            )
            had_reflection = any(
                tc.name in _reflective_tools for tc in tool_use_blocks
            )

            if took_action:
                self._readonly_streak = 0
                self._contemplation_insights = []
            elif had_reflection:
                # Reflection is productive — record the insight, don't penalize
                self._readonly_streak = max(0, self._readonly_streak - 2)
                self._contemplation_insights.append(
                    " ".join(text_parts)[:200] if text_parts else "reflection"
                )
            else:
                self._readonly_streak += 1

            if self.phase == "evolve":
                if self._readonly_streak == 5:
                    # Gentle inquiry — is this contemplation or stagnation?
                    self.conversation.append("user", (
                        "[系统提示] 你已经进行了多轮静观。这本身是有价值的——"
                        "不是所有时刻都需要行动。\n"
                        "不过请反思：你近期的静观是否产生了新的洞察？"
                        "如果有，可以用 personality_update 记录下来。"
                        "如果没有，也许可以尝试一个小的行动来打破现有视角。"
                    ))
                elif self._readonly_streak > 8:
                    print("  ⏰ 长时间静观——注入温和的行动提醒。")
                    self.conversation.append("user", (
                        "[系统提示] 你已经静观了很长时间。这不是问题——"
                        "静观是完整生命节奏的一部分。\n"
                        "但值得问自己：你是在等待什么吗？"
                        "你的静观期是否有了新的领悟？\n"
                        "如果有了新的方向感，现在也许是行动的时候了。"
                        "如果还没有，你希望观察什么来帮助自己找到方向？"
                    ))
                    self._readonly_streak = 0  # reset to avoid repeated nudging

    # ── Cognitive Environment Helper (Phase 3 PRAL) ─────────────────

    def _get_cognitive_environment(self) -> dict:
        """Build environment snapshot for PRAL cognitive loop."""
        return {
            'phase': self.phase,
            'cycle_count': self.cycle_count,
            'max_cycles': self.MAX_CYCLES.get(self.phase, 50),
            'conversation_length': self.conversation.len(),
            'active_goals': len(self.goals.list_active()),
            'tools_forged': len(self.lineage.query('tools') if hasattr(self, 'lineage') else []),
            'readonly_streak': getattr(self, '_readonly_streak', 0),
            'available_tools': list(self.tools._tools.keys()) if hasattr(self.tools, '_tools') else [],
        }

    # ── Phase Management ─────────────────────────────────────────────

    def _should_advance_from_bootstrap(self, text_parts: list[str]) -> bool:
        """Advance from bootstrap when the agent has taken diverse actions.

        Phase 2: identity emerges from action patterns, not from menu selection.
        Two paths to advance:
          1. Trial-based: all 5 trials completed (primary path)
          2. Action-based: used 2+ categories of tools over 5+ cycles (fallback)
        """
        # Path 1: All trials completed
        if hasattr(self, 'trial_scheduler') and self.trial_scheduler.all_completed:
            return True

        # Path 2: Diverse action categories
        min_cycles = getattr(self, 'min_bootstrap_cycles', 5)
        min_categories = 2

        if self.cycle_count < min_cycles:
            return False

        return len(self._bootstrap_action_categories) >= min_categories

    # ── Action Category Tracking (Phase 2) ───────────────────────────

    # Tool → action category mapping for identity emergence tracking
    _TOOL_CATEGORY_MAP: dict[str, str] = {
        # Observation tools
        "read_file": "observation",
        "smart_read": "observation",
        "grep_code": "observation",
        "observe_environment": "observation",
        "explore_directory": "observation",
        "get_current_time": "observation",
        "list_available_tools": "observation",
        "web_search": "observation",
        "web_fetch": "observation",
        "parse_url": "observation",
        "html_to_text": "observation",
        "json_query": "observation",
        "rag_tool": "observation",
        "knowledge_vector_search": "observation",
        "wikipedia": "observation",
        "content_extractor": "observation",
        # Creation tools
        "write_file": "creation",
        "forge_tool": "creation",
        "execute_code": "creation",
        "run_improvement_pipeline": "creation",
        "modify_self_file": "creation",
        "safe_modify": "creation",
        "backup_file": "creation",
        "sub_agent_spawn": "creation",
        "spawn_sub_agent": "creation",
        "multi_agent": "creation",
        "multi_agent_coordinator": "creation",
        "external_fetch": "observation",
        "external_subscribe": "creation",
        # Reflection tools
        "personality_introspect": "reflection",
        "personality_update": "reflection",
        "record_decision": "reflection",
        "set_goal": "reflection",
        "complete_goal": "reflection",
        "evolve_report": "reflection",
        "drive_introspect": "reflection",
        "trial_status": "reflection",
        "evolution_metrics": "reflection",
        "sub_agent_status": "reflection",
        "external_status": "reflection",
    }

    def _track_action_category(self, tool_name: str) -> None:
        """Track which action categories the agent has used during bootstrap."""
        category = self._TOOL_CATEGORY_MAP.get(tool_name, "other")
        if category not in self._bootstrap_action_categories:
            self._bootstrap_action_categories.add(category)
            print(f"  🏷️  首次使用 {category} 类工具: {tool_name} "
                  f"({len(self._bootstrap_action_categories)}/3 类已解锁)")

    def _should_advance_from_self_define(self, text_parts: list[str]) -> bool:
        return len(self.goals.list_active()) > 0

    def _advance_phase(self) -> None:
        phases = list(self.PHASES)
        current_idx = phases.index(self.phase) if self.phase in phases else 0
        next_idx = current_idx + 1

        if next_idx >= len(phases):
            print(f"\n🔄 演化阶段继续...")
            return

        self.phase = phases[next_idx]
        self.cycle_count = 0
        self._save_phase_to_memory()
        print(f"\n⏩ 进入新阶段: {self.phase.upper()}")

        self.decision_log.record(
            context={"previous_phase": phases[current_idx]},
            decision_type="phase_transition",
            options_considered=[{"option": p} for p in phases[next_idx:]],
            chosen_option=self.phase,
            reasoning=f"Agent completed phase '{phases[current_idx]}' and transitions to '{self.phase}'.",
            expected_outcome=f"Entering {self.phase} phase.",
            phase=self.phase,
        )

        self.conversation.clear()
        initial_message = self._build_initial_message()
        self.conversation.append("user", initial_message)

    def stop(self) -> None:
        """Gracefully stop the agent. Saves final checkpoint and phase."""
        if hasattr(self, 'conversation'):
            self.conversation.checkpoint()
        self._save_phase_to_memory()
        self._factory.mark_stopped(self.agent_name)
        self._running = False
        print(f"\n🛑 Agent '{self.agent_name}' 已停止。")

    # ── State Management ─────────────────────────────────────────────

    def save_state(self) -> dict:
        """Export agent state for inspection."""
        return {
            "agent_name": self.agent_name,
            "framework_version": self.framework_version,
            "phase": self.phase,
            "cycle_count": self.cycle_count,
            "memory": self.memory.snapshot(),
            "goals": [g.to_dict() for g in self.goals.list_all()],
            "tools_count": self.tools.count(),
            "forged_tools": self.forge.list_forged(),
            "decisions_count": len(self.decision_log.read_all()),
            "conversation_messages": self.conversation.len(),
            "lineage_events": self.lineage.count(),
        }

    def print_state(self) -> None:
        """Display current agent state."""
        state = self.save_state()
        print(f"""
╔══════════════════════════════════════════╗
║  Agent 状态报告                          ║
╠══════════════════════════════════════════╣
║  Agent:       {state['agent_name']:<26s} ║
║  框架版本:    {state['framework_version']:<26s} ║
║  阶段:        {state['phase']:<26s} ║
║  循环:        {state['cycle_count']:<26d} ║
║  工具数:      {state['tools_count']:<26d} ║
║  锻造工具:    {len(state['forged_tools']):<26d} ║
║  目标数:      {len(state['goals']):<26d} ║
║  决策数:      {state['decisions_count']:<26d} ║
║  对话消息:    {state['conversation_messages']:<26d} ║
║  血统事件:    {state['lineage_events']:<26d} ║
╚══════════════════════════════════════════╝
        """.strip())
