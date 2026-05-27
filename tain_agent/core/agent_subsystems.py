"""
AgentSubsystemsMixin — subsystem initialization and code generation wiring.
"""
import os
from pathlib import Path

from tain_agent.core.memory import Memory
from tain_agent.core.environment import apply_diversity_to_config
from tain_agent.core.llm import create_backend
from tain_agent.core.conversation import ConversationManager
from tain_agent.core.bootstrap import ToolBootstrap
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
from tain_agent.core.cognitive_loop import CognitiveLoop
from tain_agent.core.personality import Personality
from tain_agent.core.drives import DriveSystem
from tain_agent.core.trials import TrialScheduler
from tain_agent.core.external_world import ExternalWorld
from tain_agent.evolution.sub_agent import SubAgentManager


class AgentSubsystemsMixin:
    """Mixin for initializing all agent subsystems and wiring code generation."""

    def _init_subsystems(self) -> None:
        """Initialize all subsystems — the agent's body and mind."""
        # ── Create isolated workspace ────────────────────────────────
        self._workspace_path.mkdir(parents=True, exist_ok=True)
        os.environ["WORKSPACE_PATH"] = str(self._workspace_path.resolve())
        from tain_agent.storage_registry import WORKSPACE_DIRS
        for sub in WORKSPACE_DIRS:
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
            token_limit=self.config.get("conversation", {}).get("token_limit", 80000),
            model_context_window=self.config.get("conversation", {}).get("model_context_window", 131072),
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
        self.cognitive_loop = CognitiveLoop(
            memory=self.memory,
            decision_log=self.decision_log,
            goals=self.goals,
        )

        # Wire improvement loop to cognitive loop for cognitive-driven improvement
        self.cognitive_loop.connect_improvement_loop(self.improvement_loop)

        # ── Personality — emergent self-identity ──────────────────────
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
            from tain_agent.core.llm_logger import LLMLogger
            self.llm_logger = LLMLogger(Path(self.log_dir))
            self.backend.set_logger(self.llm_logger)
        else:
            api_key_env = self.config.get("llm", {}).get("api_key_env", "MINIMAX_API_KEY")
            print(f"⚠️  未设置 {api_key_env} 环境变量。Agent 将在无 LLM 状态下启动。")
            self.backend = None
            self.llm_logger = None

        # Phase 3b: Wire improvement loop code generator to LLM backend
        if self.backend:
            self._wire_improvement_loop_generator()

    def _wire_improvement_loop_generator(self) -> None:
        """Wire the improvement loop's code_generator to the LLM backend.

        This enables autonomous improvement: when the loop detects a gap,
        it can generate tool code via the LLM and run the full pipeline.
        """
        import json as _json
        backend = self.backend

        def generate_code_for_spec(spec):
            """Generate Python code for an ImprovementSpec using the LLM."""
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
                    tools=[],
                )

                text = "".join(response.text_blocks)

                if "```json" in text:
                    text = text.split("```json")[1].split("```")[0]
                elif "```" in text:
                    text = text.split("```")[1].split("```")[0]

                result = _json.loads(text.strip())
                return (
                    result.get("tool_code", ""),
                    result.get("tool_parameters", {}),
                )
            except Exception as e:
                print(f"  ⚠️  Code generation failed: {e}")
                return None

        self.improvement_loop.set_code_generator(generate_code_for_spec)
