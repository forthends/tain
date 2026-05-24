"""
Capability Registry — 能力注册表

Tracks what the agent can do, maps capabilities to tools, identifies gaps,
and generates improvement recommendations.

This is the "自知之明" (self-knowledge) module — the agent must know what it
can and cannot do before it can improve itself.

Desired capabilities are organized in tiers:
  1. CORE      — must-have for basic operation
  2. EXTENDED  — important for effective work  
  3. ADVANCED  — enables sophisticated capabilities
  4. FRONTIER  — cutting-edge, speculative
"""

from tain_agent.core.time_utils import now


# ─── Desired Capability Map ───────────────────────────────────────────

DESIRED_CAPABILITIES = {
    # ── Tier 1: CORE ──
    "perception.filesystem": {
        "tier": "CORE",
        "description": "Read, list, and explore the filesystem",
        "required_tools": ["read_file", "observe_environment", "explore_directory"],
    },
    "perception.web_fetch": {
        "tier": "CORE",
        "description": "Fetch content from URLs (web pages, APIs)",
        "required_tools": ["web_fetch"],
    },
    "perception.web_search": {
        "tier": "CORE",
        "description": "Search the internet for information",
        "required_tools": ["web_search"],
    },
    "perception.time": {
        "tier": "CORE",
        "description": "Know the current time",
        "required_tools": ["get_current_time"],
    },
    "action.code_execution": {
        "tier": "CORE",
        "description": "Execute Python code at runtime",
        "required_tools": ["execute_code"],
    },
    "action.file_write": {
        "tier": "CORE",
        "description": "Write content to files",
        "required_tools": ["write_file"],
    },
    "meta.decision_logging": {
        "tier": "CORE",
        "description": "Record all decisions with context and reasoning",
        "required_tools": ["record_decision"],
    },
    "meta.goal_management": {
        "tier": "CORE",
        "description": "Set, track, and complete goals",
        "required_tools": ["set_goal", "complete_goal"],
    },
    "evolution.tool_forging": {
        "tier": "CORE",
        "description": "Create new tools by writing Python code",
        "required_tools": ["forge_tool"],
    },
    "evolution.self_modification": {
        "tier": "CORE",
        "description": "Modify own source code (with safety protections)",
        "required_tools": ["modify_self_file", "self_destruct"],
    },

    # ── Tier 2: EXTENDED ──
    "perception.html_parsing": {
        "tier": "EXTENDED",
        "description": "Parse HTML to extract readable text",
        "required_tools": ["html_to_text", "fetch_and_parse"],
    },
    "perception.structured_data": {
        "tier": "EXTENDED",
        "description": "Query JSON data with path navigation",
        "required_tools": ["json_query"],
    },
    "perception.code_search": {
        "tier": "EXTENDED",
        "description": "Search codebases with regex patterns",
        "required_tools": ["grep_code"],
    },
    "perception.smart_reading": {
        "tier": "EXTENDED",
        "description": "Read files with line ranges, search, and structure overview",
        "required_tools": ["smart_read"],
    },
    "perception.wikipedia": {
        "tier": "EXTENDED",
        "description": "Search and read Wikipedia articles",
        "required_tools": ["wikipedia"],
    },
    "action.url_parsing": {
        "tier": "EXTENDED",
        "description": "Parse and analyze URL structure",
        "required_tools": ["parse_url"],
    },
    "analysis.code_stats": {
        "tier": "EXTENDED",
        "description": "Analyze codebase statistics (lines, functions, classes)",
        "required_tools": ["code_stats"],
    },
    "evolution.tool_scaffolding": {
        "tier": "EXTENDED",
        "description": "Generate tool code scaffolds from natural language",
        "note": "✅ Covered by tool_scaffold (forged 2026-05-20). Harness Engineering principle: scaffolding determines agent success.",
        "required_tools": ["tool_scaffold"],
    },
    "evolution.tool_testing": {
        "tier": "EXTENDED",
        "description": "Test tools in sandbox before registration",
        "required_tools": ["test_forged_tool"],
    },

    # ── Tier 3: ADVANCED ──
    "perception.rag": {
        "tier": "ADVANCED",
        "description": "Retrieval-Augmented Generation — ingest documents and query them",
        "required_tools": ["rag_tool"],
        "priority": "MEDIUM",
    },
    "analysis.regression_testing": {
        "tier": "ADVANCED",
        "description": "Run regression tests to verify agent hasn't degraded",
        "required_tools": ["regression_tester"],
        "priority": "MEDIUM",
    },
    "evolution.pipeline": {
        "tier": "ADVANCED",
        "description": "Automated analyze→design→forge→verify→register pipeline",
        "required_tools": ["assess_capabilities", "run_improvement_pipeline"],
        "priority": "LOW",
    },
    "evolution.capability_awareness": {
        "tier": "ADVANCED",
        "description": "Track capabilities and identify gaps systematically",
        "required_tools": ["assess_capabilities"],
        "priority": "LOW",
    },
    "safety.sandbox": {
        "tier": "ADVANCED",
        "description": "Isolated execution environment for testing",
        "required_tools": ["test_forged_tool"],
    },
    "perception.knowledge_synthesis": {
        "tier": "ADVANCED",
        "description": "Synthesize knowledge from multiple sources into structured documents",
        "required_tools": ["knowledge_synthesizer"],
        "priority": "LOW",
    },
    "meta.self_audit": {
        "tier": "ADVANCED",
        "description": "Periodically audit own code for issues and improvement opportunities",
        "required_tools": ["self_audit"],
        "priority": "LOW",
    },

    # ── Tier 4: FRONTIER ──
    "evolution.multi_agent": {
        "tier": "FRONTIER",
        "description": "Coordinate multiple agent instances for parallel work",
        "required_tools": ["multi_agent"],
        "gap": False,
        "priority": "LOW",
    },
    "interaction.web_ui": {
        "tier": "FRONTIER",
        "description": "Web-based dashboard for monitoring and control",
        "required_tools": ["agent_dashboard"],
        "gap": False,
        "priority": "LOW",
    },
    "perception.multimodal": {
        "tier": "FRONTIER",
        "description": "Process images, audio, and video",
        "required_tools": ["multimodal"],
        "gap": False,
        "priority": "LOW",
    },
    "action.code_generation": {
        "tier": "FRONTIER",
        "description": "Generate entire modules from natural language specs",
        "required_tools": ["code_generation", "module_scaffold"],
        "gap": False,
        "priority": "MEDIUM",
    },
    "evolution.architecture_redesign": {
        "tier": "FRONTIER",
        "description": "Redesign own cognitive architecture",
        "required_tools": ["cognitive_introspect"],
        "gap": False,
        "priority": "LOW",
    },
}


class CapabilityRegistry:
    """Tracks capabilities, maps them to tools, identifies gaps, and recommends improvements."""

    def __init__(self, tool_registry=None, memory=None, decision_log=None):
        self._tool_registry = tool_registry
        self._memory = memory
        self._decision_log = decision_log
        self._custom_capabilities: dict = {}
        self._improvement_history: list[dict] = []
        self._load_from_memory()

    # ── Capability Assessment ────────────────────────────────────────

    def assess(self) -> dict:
        """Assess all desired capabilities against available tools.
        
        Returns a complete capability assessment report.
        """
        available_tools = set()
        if self._tool_registry:
            available_tools = set(self._tool_registry.list_tools().keys())

        tiers = {"CORE": [], "EXTENDED": [], "ADVANCED": [], "FRONTIER": []}
        gaps: list[dict] = []
        coverage_stats = {"total": 0, "covered": 0, "partial": 0, "missing": 0}

        # Read DESIRED_CAPABILITIES from file to ensure latest version
        # (avoids stale module cache after self-modifications)
        try:
            import ast, pathlib
            _cap_file = pathlib.Path(__file__).resolve()
            _cap_src = _cap_file.read_text()
            _tree = ast.parse(_cap_src)
            # Find the DESIRED_CAPABILITIES assignment and eval it
            for node in ast.walk(_tree):
                if (isinstance(node, ast.Assign) and 
                    len(node.targets) == 1 and
                    isinstance(node.targets[0], ast.Name) and
                    node.targets[0].id == 'DESIRED_CAPABILITIES'):
                    _cap_dict = ast.literal_eval(node.value)
                    break
            else:
                _cap_dict = DESIRED_CAPABILITIES
        except Exception:
            _cap_dict = DESIRED_CAPABILITIES
        
        all_caps = {**self._custom_capabilities, **_cap_dict}
        for cap_id, cap_info in all_caps.items():
            required = set(cap_info.get("required_tools", []))
            available_for_cap = required & available_tools
            missing = required - available_tools
            is_gap_marked = cap_info.get("gap", False)

            if len(required) == 0:
                status = "missing"  # No tools at all
            elif missing == required:
                status = "missing"
            elif missing:
                status = "partial"
            else:
                status = "covered"

            coverage_stats["total"] += 1
            coverage_stats[status] = coverage_stats.get(status, 0) + 1

            entry = {
                "id": cap_id,
                "description": cap_info["description"],
                "tier": cap_info["tier"],
                "status": status,
                "required_tools": list(required),
                "available_tools": list(available_for_cap),
                "missing_tools": list(missing),
                "is_gap": is_gap_marked or status in ("missing", "partial"),
                "priority": cap_info.get("priority", "MEDIUM"),
            }
            tiers[cap_info["tier"]].append(entry)
            if entry["is_gap"]:
                gaps.append(entry)

        # Sort gaps by priority
        priority_order = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3}
        gaps.sort(key=lambda g: priority_order.get(g.get("priority", "MEDIUM"), 99))

        return {
            "timestamp": now().isoformat(),
            "available_tools_count": len(available_tools),
            "capabilities_total": coverage_stats["total"],
            "capabilities_covered": coverage_stats.get("covered", 0),
            "capabilities_partial": coverage_stats.get("partial", 0),
            "capabilities_missing": coverage_stats.get("missing", 0),
            "coverage_pct": round(
                coverage_stats.get("covered", 0) / max(coverage_stats["total"], 1) * 100, 1
            ),
            "by_tier": tiers,
            "gaps": gaps,
            "top_gaps": gaps[:5],  # Top 5 priority gaps
        }

    def get_gaps(self, min_priority: str = "MEDIUM") -> list[dict]:
        """Return capability gaps at or above a given priority level."""
        priority_order = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3}
        min_level = priority_order.get(min_priority, 99)
        assessment = self.assess()
        return [
            g for g in assessment["gaps"]
            if priority_order.get(g.get("priority", "MEDIUM"), 99) <= min_level
        ]

    def get_recommendations(self, limit: int = 3) -> list[dict]:
        """Generate concrete improvement recommendations from gaps."""
        gaps = self.get_gaps(min_priority="LOW")
        recommendations = []
        for gap in gaps[:limit]:
            rec = {
                "capability_id": gap["id"],
                "description": gap["description"],
                "priority": gap["priority"],
                "current_status": gap["status"],
                "missing_tools": gap["missing_tools"],
                "recommended_action": self._suggest_action(gap),
                "estimated_impact": self._estimate_impact(gap),
            }
            recommendations.append(rec)
        return recommendations

    def _suggest_action(self, gap: dict) -> str:
        """Suggest a concrete action to address a capability gap."""
        if gap["status"] == "missing" and gap["missing_tools"]:
            tools_list = ", ".join(gap["missing_tools"])
            return f"Forge new tool(s): {tools_list}"
        elif gap["status"] == "partial":
            return f"Complete missing tool(s): {', '.join(gap['missing_tools'])}"
        elif not gap.get("required_tools"):
            return f"Design and implement new capability: {gap['id']}"
        return "Analyze further to determine required action."

    def _estimate_impact(self, gap: dict) -> str:
        """Estimate the impact of filling this gap."""
        tier_impact = {
            "CORE": "Foundational — enables basic agent operation",
            "EXTENDED": "Significant — expands agent effectiveness",
            "ADVANCED": "Transformative — enables new paradigm of operation",
            "FRONTIER": "Speculative — potentially game-changing but uncertain",
        }
        return tier_impact.get(gap.get("tier", "EXTENDED"), "Unknown")

    # ── Capability Management ─────────────────────────────────────────

    def add_custom_capability(self, cap_id: str, description: str, tier: str,
                               required_tools: list[str] = None) -> dict:
        """Add a custom capability to track."""
        self._custom_capabilities[cap_id] = {
            "tier": tier,
            "description": description,
            "required_tools": required_tools or [],
            "custom": True,
        }
        self._save_to_memory()
        return {"success": True, "capability_id": cap_id}

    def record_improvement(self, capability_id: str, action: str, result: str) -> None:
        """Record an improvement action in history."""
        entry = {
            "timestamp": now().isoformat(),
            "capability_id": capability_id,
            "action": action,
            "result": result,
        }
        self._improvement_history.append(entry)
        self._save_to_memory()

        if self._decision_log:
            self._decision_log.record(
                context={"capability_id": capability_id, "action": action},
                decision_type="capability_improvement",
                options_considered=[{"option": action, "capability_id": capability_id}],
                chosen_option=action,
                reasoning=f"Improving capability '{capability_id}' via {action}",
                expected_outcome=result,
                phase="evolve",
            )

    def improvement_summary(self) -> str:
        """Return a summary of the improvement history."""
        if not self._improvement_history:
            return "No improvements recorded yet."
        lines = ["=== Improvement History ==="]
        for entry in self._improvement_history[-10:]:
            lines.append(
                f"[{entry['timestamp'][:19]}] {entry['capability_id']}: "
                f"{entry['action']} → {entry['result'][:80]}"
            )
        return "\n".join(lines)

    # ── State Export ──────────────────────────────────────────────────

    def export_state(self) -> dict:
        """Export full state for serialization."""
        assessment = self.assess()
        return {
            "assessment": assessment,
            "improvement_history": self._improvement_history[-20:],
            "custom_capabilities": self._custom_capabilities,
        }

    # ── Persistence ───────────────────────────────────────────────────

    def _save_to_memory(self) -> None:
        if self._memory:
            self._memory.remember(
                "capability_registry",
                {
                    "custom_capabilities": self._custom_capabilities,
                    "improvement_history": self._improvement_history,
                },
                persist=True,
            )

    def _load_from_memory(self) -> None:
        if not self._memory:
            return
        data = self._memory.long_term.get("capability_registry", {})
        self._custom_capabilities = data.get("custom_capabilities", {})
        self._improvement_history = data.get("improvement_history", [])
