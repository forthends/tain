"""
Cognitive Loop — 认知循环 (Phase 3: Architecture Redesign)

Formalizes the agent's cognitive architecture as a PRAL cycle:
  Perceive → Reason → Act → Learn

This is the "二生三" layer — from the duality of agent+environment emerges
the tripartite structure of perception, reasoning, and action, plus the
recursive fourth phase of learning that enables self-improvement.

Architecture:
  ┌──────────────────────────────────────────────┐
  │              COGNITIVE LOOP                   │
  │                                               │
  │  ┌──────────┐    ┌──────────┐                 │
  │  │ PERCEIVE │───▶│  REASON  │                 │
  │  │ (gather) │    │ (decide) │                 │
  │  └──────────┘    └──────────┘                 │
  │       ▲                │                      │
  │       │                ▼                      │
  │  ┌──────────┐    ┌──────────┐                 │
  │  │  LEARN   │◀───│   ACT    │                 │
  │  │ (update) │    │ (execute)│                 │
  │  └──────────┘    └──────────┘                 │
  │                                               │
  └──────────────────────────────────────────────┘

Key additions over the implicit v0.2 architecture:
  1. Explicit cognitive state tracking (what is the agent thinking about?)
  2. Reflection phase: after acting, analyze results before next perception
  3. Learning integration: tool outcomes feed back into memory
  4. Cognitive metrics: reasoning depth, action diversity, learn rate

This module builds ON TOP OF the protected agent.py bootstrap protocol,
adding cognitive structure without modifying the core.
"""

from dataclasses import dataclass, field, asdict
from tain_agent.core.time_utils import now
from typing import Optional, Any
from enum import Enum


# ─── Cognitive State ──────────────────────────────────────────────────

class CognitivePhase(Enum):
    """Current phase of the cognitive cycle."""
    PERCEIVE = "perceive"
    REASON = "reason"
    ACT = "act"
    LEARN = "learn"
    IDLE = "idle"


@dataclass
class CognitiveState:
    """Snapshot of the agent's cognitive state at a point in time.
    
    This is the "自知之明" (self-awareness) — the agent knowing
    what it is currently thinking about and how it got there.
    """
    phase: CognitivePhase = CognitivePhase.IDLE
    cycle_count: int = 0
    current_goal: Optional[str] = None
    last_action: Optional[str] = None
    last_action_result: Optional[str] = None
    tools_used_this_cycle: list[str] = field(default_factory=list)
    reasoning_depth: int = 0  # estimated reasoning steps
    confidence: float = 0.5   # confidence in next action (0-1)
    timestamp: str = ""

    def to_dict(self) -> dict:
        """Serialize cognitive state to a dictionary for introspection."""
        d = asdict(self)
        d['phase'] = self.phase.value
        return d


# ─── Cognitive Loop ───────────────────────────────────────────────────

class CognitiveLoop:
    """The PRAL cognitive cycle: Perceive→Reason→Act→Learn.
    
    This is the architecture redesign's core contribution — making
    explicit what was previously an implicit loop inside agent.py's
    run() method. By externalizing the cognitive cycle, we enable:
    
    - Cognitive state introspection (what am I thinking?)
    - Phase-level metrics (how deep is my reasoning?)
    - Reflection-based improvement (did that action work?)
    - Pattern recognition across cycles (am I repeating myself?)
    """

    def __init__(self, memory=None, decision_log=None, goals=None, improvement_loop=None):
        self._memory = memory
        self._decision_log = decision_log
        self._goals = goals
        self._improvement_loop = improvement_loop  # Optional: ImprovementLoop for cognitive-driven improvement
        
        # Cognitive state
        self.state = CognitiveState()
        self.state.timestamp = now().isoformat()
        
        # History
        self._cycle_history: list[CognitiveState] = []
        self._reflection_log: list[dict] = []
        
        # Metrics
        self._total_cycles = 0
        self._action_history: list[str] = []
        self._all_tools_used: set[str] = set()  # cumulative distinct tools
        self._tool_success_rates: dict[str, tuple[int, int]] = {}  # tool → (successes, total)
        self._total_tools_available: int = 0

        # Adaptive suggestion tracking (v0.7.0)
        self._act_count: int = 0
        self._reflect_count: int = 0
        self._suggestion_config: dict = {}
        self._agent_mode: str = "chaos"
        self._agent_role: str = ""

    def configure_suggestions(self, config: dict, agent_mode: str = "chaos",
                              agent_role: str = "") -> None:
        """Load cognitive suggestion configuration and agent identity."""
        self._suggestion_config = config
        self._agent_mode = agent_mode
        self._agent_role = agent_role

    def _get_effective_pressures(self) -> dict:
        """Compute effective suggestion pressures for the current agent.

        Merges mode defaults + role overrides + adaptive adjustments.
        """
        cfg = self._suggestion_config
        if not cfg:
            return {"act_pressure": 0.5, "explore_pressure": 0.4, "reflect_ratio": 0.4}

        modes = cfg.get("modes", {})
        mode_cfg = modes.get(self._agent_mode, modes.get("chaos", {}))
        act = mode_cfg.get("act_pressure", 0.5)
        explore = mode_cfg.get("explore_pressure", 0.4)
        reflect = mode_cfg.get("reflect_ratio", 0.4)

        # Apply role override
        role = self._agent_role
        if role:
            role_overrides = mode_cfg.get("role_overrides", {})
            override = role_overrides.get(role, {})
            if override:
                act = override.get("act_pressure", act)
                explore = override.get("explore_pressure", explore)
                reflect = override.get("reflect_ratio", reflect)

        # Apply adaptive adjustment
        adaptive = cfg.get("adaptive", {})
        if adaptive.get("enabled", True):
            window = adaptive.get("observation_window", 5)
            threshold = adaptive.get("act_drought_threshold", 0.2)
            rate = adaptive.get("pressure_adjustment_rate", 0.1)

            total_recent = self._act_count + self._reflect_count
            if total_recent >= window:
                act_ratio = self._act_count / max(total_recent, 1)
                if act_ratio < threshold:
                    act = min(0.95, act + rate)
                    reflect = max(0.05, reflect - rate)

        return {
            "act_pressure": round(act, 3),
            "explore_pressure": round(explore, 3),
            "reflect_ratio": round(reflect, 3),
        }

    # ── Perceive ───────────────────────────────────────────────────
    
    def perceive(self, environment: dict, conversation_summary: str = "") -> dict:
        """Gather all inputs before reasoning.
        
        Args:
            environment: Current environment state (files, tools, etc.)
            conversation_summary: Summary of recent conversation
            
        Returns:
            Structured perception of the current situation.
        """
        self.state.phase = CognitivePhase.PERCEIVE
        
        # Count available tools
        tool_count = environment.get('tools_count', 0)
        
        # Current goal
        goal = None
        if self._goals:
            current = self._goals.get_current()
            if current:
                goal = current.description
        self.state.current_goal = goal
        
        perception = {
            "phase": "perceive",
            "tool_count": tool_count,
            "current_goal": goal,
            "conversation_length": len(conversation_summary) if conversation_summary else 0,
            "timestamp": now().isoformat(),
        }
        
        return perception
    
    # ── Reason ─────────────────────────────────────────────────────
    
    def reason(self, perception: dict, available_actions: list[str] = None) -> dict:
        """Analyze the situation and decide what to do.
        
        This is where the agent asks itself: given what I perceive,
        what is the most impactful action I can take toward my goal?
        
        Args:
            perception: Output from perceive()
            available_actions: List of available action types
            
        Returns:
            Reasoning result with recommended action.
        """
        self.state.phase = CognitivePhase.REASON
        
        # Estimate reasoning depth from available context
        depth = 1
        if perception.get('current_goal'):
            depth += 1
        if perception.get('tool_count', 0) > 30:
            depth += 1
        if self._total_cycles > 0:
            depth += min(self._total_cycles // 5, 3)
        self.state.reasoning_depth = depth
        
        reasoning = {
            "phase": "reason",
            "depth": depth,
            "has_goal": perception.get('current_goal') is not None,
            "available_actions": available_actions or [],
            "previous_action": self.state.last_action,
            "recommendation": self._generate_recommendation(perception),
            "timestamp": now().isoformat(),
        }
        
        return reasoning
    
    def _generate_recommendation(self, perception: dict) -> str:
        """Generate a recommendation based on state and adaptive pressures."""
        pressures = self._get_effective_pressures()

        if not perception.get('current_goal'):
            return "set_goal: No active goal — define one."

        # Check if stuck in a loop
        if len(self._action_history) >= 3:
            last_three = self._action_history[-3:]
            if len(set(last_three)) == 1:
                return f"try_different: Repeating {last_three[0]}. Try a different action."

        if self._total_cycles < 3:
            return "explore: Early cycles — gather information."

        # v0.7.0: Mode-aware suggestion
        if pressures["act_pressure"] < 0.3 and pressures["reflect_ratio"] > 0.5:
            return "reflect: What deeper patterns do you observe? What are you learning?"

        return "act: Take action toward current goal."
    
    # ── Act ────────────────────────────────────────────────────────
    
    def act(self, action_name: str, action_result: Any = None) -> dict:
        """Execute or record an action.
        
        Args:
            action_name: Name of the action/tool being executed
            action_result: Result of the action (if already executed)
            
        Returns:
            Action record.
        """
        self.state.phase = CognitivePhase.ACT
        self.state.last_action = action_name
        self.state.tools_used_this_cycle.append(action_name)
        self._action_history.append(action_name)
        self._all_tools_used.add(action_name)
        
        # Track tool success rates
        if action_result is not None:
            success = not isinstance(action_result, str) or not action_result.startswith('Error')
            prev = self._tool_success_rates.get(action_name, (0, 0))
            self._tool_success_rates[action_name] = (
                prev[0] + (1 if success else 0),
                prev[1] + 1,
            )

        # v0.7.0: Track for adaptive suggestion
        self._act_count += 1

        action = {
            "phase": "act",
            "action": action_name,
            "result_summary": str(action_result)[:200] if action_result else None,
            "tool_success_rate": self._get_tool_rate(action_name),
            "timestamp": now().isoformat(),
        }
        
        return action
    
    def _get_tool_rate(self, tool_name: str) -> Optional[float]:
        """Get success rate for a tool."""
        prev = self._tool_success_rates.get(tool_name)
        if prev and prev[1] > 0:
            return round(prev[0] / prev[1], 2)
        return None
    
    # ── Learn ──────────────────────────────────────────────────────
    
    def learn(self, actions) -> dict:
        """Reflect on what happened and update internal models.
        
        This is the key addition over the v0.2 architecture.
        After acting, the agent should ask: did that work?
        What can I learn from it?
        
        Args:
            actions: A single action dict from act(), OR a list of results 
                     from agent.py's _execute_tool_calls().
            
        Returns:
            Learning outcome with insights.
        """
        self.state.phase = CognitivePhase.LEARN
        
        # Support both single action dict (from act()) and list (from agent.py)
        if isinstance(actions, list):
            for item in actions:
                if isinstance(item, dict) and item.get('action'):
                    action = item
                    break
            else:
                if actions:
                    action = {"action": actions[0].get('tool_name', 'unknown') if isinstance(actions[0], dict) else 'batch'}
                else:
                    action = {"action": "no_action"}
        else:
            action = actions
        
        # Calculate confidence
        tool_name = action.get('action', '')

        # v0.7.0: Track reflective tools for adaptive suggestions
        _reflective = {"personality_introspect", "personality_update", "set_goal",
                       "complete_goal", "evolve_report", "assess_capabilities",
                       "pipeline_status", "record_decision"}
        if isinstance(tool_name, str) and tool_name in _reflective:
            self._reflect_count += 1

        rate = self._get_tool_rate(tool_name)
        if rate is not None:
            self.state.confidence = rate
        elif self._total_cycles > 0:
            # General confidence grows with experience
            self.state.confidence = min(0.8, 0.3 + self._total_cycles * 0.05)
        
        # Generate reflection
        reflection = self._reflect(action)
        if reflection:
            self._reflection_log.append({
                "cycle": self._total_cycles,
                "action": tool_name,
                "reflection": reflection,
                "timestamp": now().isoformat(),
            })
        
        learning = {
            "phase": "learn",
            "confidence": self.state.confidence,
            "reflection": reflection,
            "total_cycles": self._total_cycles,
            "tools_learned": len(self._tool_success_rates),
            "timestamp": now().isoformat(),
        }
        
        # ── Cognitive-driven improvement (Phase B: loop unification) ──
        # After learning from each cycle, check if systemic improvement is needed.
        # This replaces the timer-driven background thread with cognition-driven gating.
        improvement_result = None
        if self._improvement_loop:
            try:
                improvement_result = self._improvement_loop.execute_once_if_needed()
                learning["improvement_triggered"] = improvement_result.get("triggered", False)
                if improvement_result.get("triggered"):
                    learning["improvement_result"] = improvement_result.get("result", {}).get("summary", "")
            except Exception:
                learning["improvement_triggered"] = False  # Graceful degradation
        
        return learning
    
    def _reflect(self, action: dict) -> Optional[str]:
        """Generate a reflection on the action."""
        tool_name = action.get('action', '')
        rate = self._get_tool_rate(tool_name)
        
        if rate is not None and rate < 0.5:
            return f"Tool '{tool_name}' has low success rate ({rate:.0%}). Consider alternatives."
        
        if len(self._action_history) >= 5:
            recent = self._action_history[-5:]
            reads = sum(1 for a in recent if a in 
                       ('read_file', 'smart_read', 'observe_environment', 'explore_directory'))
            if reads >= 4:
                pressures = self._get_effective_pressures()
                if pressures.get("reflect_ratio", 0.4) > 0.5:
                    return ("High reflection ratio — consistent with your reflective nature. "
                            "What insights have emerged from this observation period?")
                return "High read-to-act ratio — consider taking more actions."
        
        return None
    
    # ── Public API for agent.py ─────────────────────────────────────
    # These methods provide the interface that agent.py expects.
    
    def connect_improvement_loop(self, improvement_loop) -> None:
        """Connect to the improvement loop for cognitive-driven improvement.
        
        Once connected, the learn() phase will automatically trigger 
        improvement cycles when the need_score exceeds threshold.
        Call this after both CognitiveLoop and ImprovementLoop are initialized.
        
        Args:
            improvement_loop: tain_agent.evolution.improvement_loop.ImprovementLoop instance
        """
        self._improvement_loop = improvement_loop
    
    def get_tool_success_rates(self) -> dict:
        """Get per-tool success rate statistics from this session.
        
        Returns:
            dict mapping tool_name -> {"successes": int, "total": int, "rate": float}
        """
        return {
            tool: {
                "successes": s,
                "total": t,
                "rate": s / max(t, 1),
            }
            for tool, (s, t) in self._tool_success_rates.items()
        }
    
    def record_action(self, action_name: str, action_result: str = "") -> dict:
        """Record an action that was executed by agent.py.
        
        This is the public interface agent.py calls after each tool execution.
        Wraps the internal act() method.
        
        Args:
            action_name: Name of the tool that was called
            action_result: String result of the tool call
            
        Returns:
            Action record dict.
        """
        return self.act(action_name, action_result)
    
    def reflect(self) -> Optional[str]:
        """Generate a cognitive reflection based on recent action history.
        
        Called by agent.py after learn() to get actionable insights
        that are injected back into the conversation.
        
        Returns:
            Reflection string, or None if nothing to report.
        """
        if not self._action_history:
            return None
        
        recent_action = {"action": self._action_history[-1]}
        return self._reflect(recent_action)
    
    def log_reflection(self, reflection: str) -> None:
        """Log a reflection to the internal reflection log.
        
        Called by agent.py to persist cognitive reflections.
        
        Args:
            reflection: The reflection text to log.
        """
        self._reflection_log.append({
            "cycle": self._total_cycles,
            "reflection": reflection,
            "timestamp": now().isoformat(),
        })
    
    # ── Full Cycle ─────────────────────────────────────────────────
    
    def run_cycle(self, environment: dict, conversation_summary: str = "",
                  action_name: str = "", action_result: Any = None) -> dict:
        """Run one complete PRAL cycle.
        
        Args:
            environment: Current environment state
            conversation_summary: Recent conversation summary
            action_name: Name of action to execute (or empty to skip)
            action_result: Result of the action
            
        Returns:
            Full cycle report with all phase outputs.
        """
        self._total_cycles += 1
        self.state.cycle_count = self._total_cycles
        self.state.tools_used_this_cycle = []
        
        perception = self.perceive(environment, conversation_summary)
        reasoning = self.reason(perception, list(environment.get('available_tools', [])))
        
        action = None
        if action_name:
            action = self.act(action_name, action_result)
        
        learning = self.learn(action or {"action": "none"})
        
        # Save state snapshot
        self.state.timestamp = now().isoformat()
        self._cycle_history.append(CognitiveState(
            phase=self.state.phase,
            cycle_count=self.state.cycle_count,
            current_goal=self.state.current_goal,
            last_action=self.state.last_action,
            tools_used_this_cycle=list(self.state.tools_used_this_cycle),
            reasoning_depth=self.state.reasoning_depth,
            confidence=self.state.confidence,
            timestamp=self.state.timestamp,
        ))
        
        # Keep only last 100 cycles
        if len(self._cycle_history) > 100:
            self._cycle_history = self._cycle_history[-100:]
        
        self.state.phase = CognitivePhase.IDLE
        
        return {
            "cycle": self._total_cycles,
            "goal": self.state.current_goal,
            "perception": perception,
            "reasoning": reasoning,
            "action": action,
            "learning": learning,
            "cognitive_state": self.state.to_dict(),
        }
    
    # ── Introspection ──────────────────────────────────────────────
    
    def introspect(self) -> dict:
        """Deep self-analysis of cognitive patterns.
        
        Returns a structured report of the agent's cognitive health,
        patterns, and potential issues.
        """
        # Action diversity — dual metric: cumulative (session breadth) and recent (short-term variety)
        cumulative = len(self._all_tools_used) / max(self._total_tools_available, 1)
        recent_actions = self._action_history[-20:]
        recent_diversity = self._entropy(recent_actions)
        combined = 0.6 * cumulative + 0.4 * recent_diversity
        
        # Top tools
        tool_stats = {}
        for name, (successes, total) in self._tool_success_rates.items():
            tool_stats[name] = {
                "uses": total,
                "success_rate": round(successes / total, 2) if total > 0 else 0,
            }
        
        # Recent patterns
        pattern = self._detect_pattern(recent_actions)
        
        # Reflections
        recent_reflections = self._reflection_log[-5:]
        
        return {
            "cognitive_health": {
                "total_cycles": self._total_cycles,
                "current_confidence": self.state.confidence,
                "action_diversity": {
                    "cumulative": round(cumulative, 2),
                    "recent": round(recent_diversity, 2),
                    "combined": round(combined, 2),
                    "distinct_tools_used": len(self._all_tools_used),
                    "total_tools_available": self._total_tools_available,
                },
            },
            "tool_performance": tool_stats,
            "patterns_detected": pattern,
            "recent_reflections": recent_reflections,
            "recommendation": self._health_recommendation(combined, cumulative, recent_diversity),
        }
    
    def _detect_pattern(self, actions: list[str]) -> Optional[str]:
        """Detect repeated action patterns."""
        if len(actions) < 6:
            return None
        
        # Look for 3-repeat patterns
        for i in range(len(actions) - 5):
            seq = actions[i:i+3]
            if seq == actions[i+3:i+6]:
                return f"Repeating sequence: {seq}"
        
        return None
    
    def _health_recommendation(self, combined: float, cumulative: float,
                                recent: float) -> str:
        """Generate cognitive health recommendation using dual-metric diversity."""
        parts = []
        if recent < 0.2 and self._total_cycles > 10:
            parts.append("Low recent diversity — vary your next few tool choices")
        if cumulative < 0.2 and self._total_cycles > 10:
            parts.append("Low cumulative diversity — explore new tool types")
        if cumulative > 0.3 and recent < 0.2:
            parts.append("Cumulative healthy but recent low — small variety boost needed")
        if self.state.confidence < 0.3:
            parts.append("Low confidence — consider simpler, more reliable actions")
        if not parts:
            return "Cognitive health: good."
        return " | ".join(parts)

    def _entropy(self, actions: list[str]) -> float:
        """Shannon entropy of action distribution (0-1, normalized)."""
        from math import log2
        if not actions:
            return 0.0
        counts = {}
        for a in actions:
            counts[a] = counts.get(a, 0) + 1
        n = len(actions)
        entropy = -sum((c / n) * log2(c / n) for c in counts.values())
        max_entropy = log2(min(len(counts), n))
        return entropy / max_entropy if max_entropy > 0 else 0.0
    
    # ── State Export ───────────────────────────────────────────────
    
    def snapshot(self) -> dict:
        """Export full cognitive state for inspection."""
        return {
            "state": self.state.to_dict(),
            "total_cycles": self._total_cycles,
            "recent_history": [s.to_dict() for s in self._cycle_history[-10:]],
            "reflection_count": len(self._reflection_log),
            "tool_performance": {
                name: {"successes": s, "total": t}
                for name, (s, t) in self._tool_success_rates.items()
            },
        }
