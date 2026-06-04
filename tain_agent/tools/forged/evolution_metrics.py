"""
Evolution Metrics — 进化质量指标

Phase 2 milestone 2.4: quantitative self-evaluation system.

Collects metrics across 5 categories (knowledge garden, tool efficacy, code health,
personality development, evolution efficiency), compares between versions, and
generates degradation alerts.

Usable both as an importable module (by reporter.py) and as a forged tool
(via main() entry point).
"""

import json
import os
import re
import subprocess
from pathlib import Path
from datetime import datetime, timezone
from collections import defaultdict
from typing import Optional

from tain_agent.core.time_utils import now


# ─── Data classes ──────────────────────────────────────────────────────

class MetricsSnapshot:
    """A point-in-time snapshot of all evolution metrics."""

    def __init__(self, version: str = "unknown"):
        self.version = version
        self.collected_at = now().isoformat()

        # Knowledge garden
        self.knowledge_nodes: int = 0
        self.knowledge_edges: int = 0
        self.knowledge_isolated_ratio: float = 0.0
        self.knowledge_fresh_ratio: float = 0.0

        # Tool efficacy
        self.tool_total_calls: int = 0
        self.tool_success_rate: float = 1.0
        self.tool_avg_response_ms: float = 0.0
        self.tool_dead_ratio: float = 0.0
        self.tool_total_count: int = 0
        self.tool_dead_count: int = 0

        # Code health
        self.code_total_lines: int = 0
        self.code_py_files: int = 0
        self.code_test_files: int = 0
        self.code_duplication_estimate: float = 0.0

        # Personality development
        self.personality_dimensions_developed: int = 0
        self.personality_total_dimensions: int = 7
        self.personality_high_confidence_traits: int = 0
        self.personality_total_traits: int = 0

        # Evolution efficiency
        self.evolution_total_cycles: int = 0
        self.evolution_improvements_made: int = 0
        self.evolution_improvement_rate: float = 0.0
        self.evolution_streak_no_improvement: int = 0

        # Git history
        self.git_commit_count: int = 0
        self.git_days_since_last_commit: float = 0.0

    def to_dict(self) -> dict:
        return {
            "version": self.version,
            "collected_at": self.collected_at,
            "knowledge_garden": {
                "nodes": self.knowledge_nodes,
                "edges": self.knowledge_edges,
                "isolated_ratio": round(self.knowledge_isolated_ratio, 3),
                "fresh_ratio": round(self.knowledge_fresh_ratio, 3),
            },
            "tool_efficacy": {
                "total_calls": self.tool_total_calls,
                "success_rate": round(self.tool_success_rate, 3),
                "avg_response_ms": round(self.tool_avg_response_ms, 1),
                "dead_ratio": round(self.tool_dead_ratio, 3),
                "total_tools": self.tool_total_count,
                "dead_tools": self.tool_dead_count,
            },
            "code_health": {
                "total_lines": self.code_total_lines,
                "py_files": self.code_py_files,
                "test_files": self.code_test_files,
                "duplication_estimate": round(self.code_duplication_estimate, 3),
            },
            "personality": {
                "dimensions_developed": self.personality_dimensions_developed,
                "total_dimensions": self.personality_total_dimensions,
                "high_confidence_traits": self.personality_high_confidence_traits,
                "total_traits": self.personality_total_traits,
                "development_ratio": round(
                    self.personality_dimensions_developed / max(self.personality_total_dimensions, 1), 2
                ),
            },
            "evolution_efficiency": {
                "total_cycles": self.evolution_total_cycles,
                "improvements_made": self.evolution_improvements_made,
                "improvement_rate": round(self.evolution_improvement_rate, 3),
                "streak_no_improvement": self.evolution_streak_no_improvement,
            },
            "git": {
                "commit_count": self.git_commit_count,
                "days_since_last_commit": round(self.git_days_since_last_commit, 1),
            },
        }

    @classmethod
    def from_dict(cls, data: dict) -> "MetricsSnapshot":
        s = cls(version=data.get("version", "unknown"))
        s.collected_at = data.get("collected_at", "")
        kg = data.get("knowledge_garden", {})
        s.knowledge_nodes = kg.get("nodes", 0)
        s.knowledge_edges = kg.get("edges", 0)
        s.knowledge_isolated_ratio = kg.get("isolated_ratio", 0)
        s.knowledge_fresh_ratio = kg.get("fresh_ratio", 0)
        te = data.get("tool_efficacy", {})
        s.tool_total_calls = te.get("total_calls", 0)
        s.tool_success_rate = te.get("success_rate", 1.0)
        s.tool_avg_response_ms = te.get("avg_response_ms", 0)
        s.tool_dead_ratio = te.get("dead_ratio", 0)
        s.tool_total_count = te.get("total_tools", 0)
        s.tool_dead_count = te.get("dead_tools", 0)
        ch = data.get("code_health", {})
        s.code_total_lines = ch.get("total_lines", 0)
        s.code_py_files = ch.get("py_files", 0)
        s.code_test_files = ch.get("test_files", 0)
        s.code_duplication_estimate = ch.get("duplication_estimate", 0)
        p = data.get("personality", {})
        s.personality_dimensions_developed = p.get("dimensions_developed", 0)
        s.personality_total_dimensions = p.get("total_dimensions", 7)
        s.personality_high_confidence_traits = p.get("high_confidence_traits", 0)
        s.personality_total_traits = p.get("total_traits", 0)
        ee = data.get("evolution_efficiency", {})
        s.evolution_total_cycles = ee.get("total_cycles", 0)
        s.evolution_improvements_made = ee.get("improvements_made", 0)
        s.evolution_improvement_rate = ee.get("improvement_rate", 0)
        s.evolution_streak_no_improvement = ee.get("streak_no_improvement", 0)
        g = data.get("git", {})
        s.git_commit_count = g.get("commit_count", 0)
        s.git_days_since_last_commit = g.get("days_since_last_commit", 0)
        return s


class MetricsComparison:
    """Comparison between two metrics snapshots."""

    def __init__(self, from_snapshot: MetricsSnapshot, to_snapshot: MetricsSnapshot):
        self.version_from = from_snapshot.version
        self.version_to = to_snapshot.version
        self.collected_at = now().isoformat()

        self.deltas: dict[str, dict] = {}
        self._compute(from_snapshot, to_snapshot)

    def _compute(self, a: MetricsSnapshot, b: MetricsSnapshot) -> None:
        """Compute all deltas between two snapshots."""
        pairs = [
            ("knowledge_nodes", a.knowledge_nodes, b.knowledge_nodes, "节点数"),
            ("knowledge_edges", a.knowledge_edges, b.knowledge_edges, "边数"),
            ("knowledge_isolated_ratio", a.knowledge_isolated_ratio, b.knowledge_isolated_ratio, "孤立比例", True),
            ("knowledge_fresh_ratio", a.knowledge_fresh_ratio, b.knowledge_fresh_ratio, "新鲜度"),
            ("tool_success_rate", a.tool_success_rate, b.tool_success_rate, "成功率"),
            ("tool_avg_response_ms", a.tool_avg_response_ms, b.tool_avg_response_ms, "响应时间", True),
            ("tool_dead_ratio", a.tool_dead_ratio, b.tool_dead_ratio, "死工具比例", True),
            ("tool_total_count", a.tool_total_count, b.tool_total_count, "工具总数"),
            ("code_total_lines", a.code_total_lines, b.code_total_lines, "代码行数"),
            ("code_py_files", a.code_py_files, b.code_py_files, "Python文件"),
            ("personality_dimensions_developed", a.personality_dimensions_developed, b.personality_dimensions_developed, "人格维度"),
            ("personality_high_confidence_traits", a.personality_high_confidence_traits, b.personality_high_confidence_traits, "高置信特质"),
            ("evolution_improvement_rate", a.evolution_improvement_rate, b.evolution_improvement_rate, "改进率"),
            ("evolution_streak_no_improvement", a.evolution_streak_no_improvement, b.evolution_streak_no_improvement, "无改进连续", True),
        ]

        for key, old_val, new_val, label, *flags in pairs:
            lower_is_better = flags[0] if flags else False
            delta = new_val - old_val
            if old_val != 0:
                pct = (delta / old_val) * 100
            else:
                pct = 100.0 if new_val > 0 else 0.0

            trend = self._trend(delta, lower_is_better)
            self.deltas[key] = {
                "label": label,
                "old": old_val,
                "new": new_val,
                "delta": delta,
                "pct_change": round(pct, 1),
                "trend": trend,
            }

    @staticmethod
    def _trend(delta: float, lower_is_better: bool = False) -> str:
        """Classify the trend direction."""
        if lower_is_better:
            if delta < -0.01:
                return "improving"
            elif delta > 0.01:
                return "declining"
            return "stable"
        else:
            if delta > 0.01:
                return "improving"
            elif delta < -0.01:
                return "declining"
            return "stable"

    def get_degradations(self) -> list[dict]:
        """Return list of metrics showing degradation."""
        alerts = []
        for key, d in self.deltas.items():
            if d["trend"] == "declining":
                severity = "warning"
                # More severe if declining more than 20%
                if abs(d["pct_change"]) > 20:
                    severity = "critical"
                alerts.append({
                    "metric": key,
                    "label": d["label"],
                    "from": d["old"],
                    "to": d["new"],
                    "change_pct": d["pct_change"],
                    "severity": severity,
                })
        return alerts

    def format_dashboard(self) -> str:
        """Format a version-to-version comparison dashboard."""
        lines = []
        lines.append(f"```")
        lines.append(f"{self.version_from} → {self.version_to} 进化仪表盘")
        lines.append(f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
        lines.append("")

        categories = [
            ("知识园林", ["knowledge_nodes", "knowledge_edges", "knowledge_isolated_ratio", "knowledge_fresh_ratio"]),
            ("工具效能", ["tool_total_count", "tool_success_rate", "tool_avg_response_ms", "tool_dead_ratio"]),
            ("代码健康", ["code_total_lines", "code_py_files"]),
            ("人格发展", ["personality_dimensions_developed", "personality_high_confidence_traits"]),
            ("进化效率", ["evolution_improvement_rate", "evolution_streak_no_improvement"]),
        ]

        for cat_name, keys in categories:
            parts = []
            for key in keys:
                if key not in self.deltas:
                    continue
                d = self.deltas[key]
                trend_symbol = {"improving": "↑", "declining": "↓", "stable": "→"}[d["trend"]]
                if isinstance(d["old"], float):
                    parts.append(f"{d['label']}: {d['old']:.2f} → {d['new']:.2f} {trend_symbol}")
                else:
                    parts.append(f"{d['label']}: {d['old']} → {d['new']} {trend_symbol}")
            if parts:
                lines.append(f"{cat_name}:  {' |  '.join(parts)}")

        lines.append(f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
        lines.append(f"```")
        return "\n".join(lines)

    def to_dict(self) -> dict:
        return {
            "version_from": self.version_from,
            "version_to": self.version_to,
            "collected_at": self.collected_at,
            "deltas": self.deltas,
            "degradations": self.get_degradations(),
        }


# ─── Metrics Collector ─────────────────────────────────────────────────

class MetricsCollector:
    """Collects evolution metrics from all available data sources.

    Designed to be resilient — if a data source is unavailable (e.g.,
    a forged tool hasn't been created yet), the corresponding metric
    defaults to 0 or N/A without raising an error.
    """

    def __init__(self, base_dir: str = ".", tool_registry=None,
                 personality=None, improvement_loop=None,
                 decision_log=None, memory=None, agent_name: str = ""):
        self.base_dir = Path(base_dir).resolve()
        self.tool_registry = tool_registry
        self.personality = personality
        self.improvement_loop = improvement_loop
        self.decision_log = decision_log
        self.memory = memory
        self.agent_name = agent_name

    def collect(self, version: str = "unknown") -> MetricsSnapshot:
        """Collect all available metrics into a snapshot."""
        s = MetricsSnapshot(version=version)

        self._collect_knowledge_garden(s)
        self._collect_tool_efficacy(s)
        self._collect_code_health(s)
        self._collect_personality(s)
        self._collect_evolution_efficiency(s)
        self._collect_git_stats(s)

        return s

    # ── Knowledge Garden ────────────────────────────────────────────

    def _collect_knowledge_garden(self, s: MetricsSnapshot) -> None:
        """Try to collect knowledge graph metrics from forged tools."""
        try:
            import tain_agent.tools.forged.knowledge_graph as kg
            # Auto-sync knowledge dir before reading stats to ensure graph.json exists
            kg.sync_from_markdown()
            stats = kg.get_stats() if hasattr(kg, 'get_stats') else {}
            s.knowledge_nodes = stats.get("total_nodes", 0)
            s.knowledge_edges = stats.get("total_edges", 0)
            s.knowledge_isolated_ratio = stats.get("isolated_ratio", 0.0)
        except (ImportError, AttributeError, Exception):
            pass

        try:
            import tain_agent.tools.forged.knowledge_freshness as kf
            result = kf.check_freshness() if hasattr(kf, 'check_freshness') else {}
            s.knowledge_fresh_ratio = result.get("fresh_ratio", 0.0)
        except (ImportError, AttributeError, Exception):
            pass

    # ── Tool Efficacy ───────────────────────────────────────────────

    def _collect_tool_efficacy(self, s: MetricsSnapshot) -> None:
        """Collect tool usage statistics with filesystem fallback."""
        # Primary: use injected ToolRegistry
        if self.tool_registry:
            try:
                tools = self.tool_registry.list_tools()
                s.tool_total_count = len(tools)
            except Exception:
                pass

        # Fallback: scan forged_tools directories on filesystem
        if s.tool_total_count == 0:
            candidate_dirs = []
            # Current agent's workspace takes priority
            if self.agent_name:
                ft = self.base_dir / "agent_workspace" / self.agent_name / "forged_tools"
                if ft.exists():
                    candidate_dirs.append(ft)
            # Also scan built-in forged tools for comprehensive count
            candidate_dirs.append(
                self.base_dir / "tain_agent" / "tools" / "forged",
            )
            for tools_dir in candidate_dirs:
                if tools_dir.exists():
                    py_files = [f for f in tools_dir.glob("*.py")
                               if not f.name.startswith("_")]
                    s.tool_total_count = len(py_files)
                    break

        # Check decision log for tool call records
        if self.decision_log:
            try:
                all_decisions = self.decision_log.read_all()
                tool_calls = [d for d in all_decisions if d.get("decision_type") == "tool_call"]
                s.tool_total_calls = len(tool_calls)

                successes = 0
                for d in tool_calls:
                    outcome = d.get("actual_outcome", "")
                    if outcome and "SUCCESS" in str(outcome).upper():
                        successes += 1
                if s.tool_total_calls > 0:
                    s.tool_success_rate = successes / s.tool_total_calls
            except (AttributeError, Exception):
                pass

        # Dead tool detection by file modification time (> 30 days)
        forged_dirs = []
        if self.agent_name:
            ft = self.base_dir / "agent_workspace" / self.agent_name / "forged_tools"
            if ft.exists():
                forged_dirs.append(ft)
        forged_dirs.append(
            self.base_dir / "tain_agent" / "tools" / "forged",
        )
        now_ts = now()
        dead_count = 0
        for forged_dir in forged_dirs:
            if not forged_dir.exists():
                continue
            for f in forged_dir.glob("*.py"):
                if f.name.startswith("_"):
                    continue
                try:
                    mtime = datetime.fromtimestamp(f.stat().st_mtime, tz=timezone.utc)
                    age_days = (now_ts - mtime.replace(tzinfo=None)).total_seconds() / 86400
                    if age_days > 30:
                        dead_count += 1
                except Exception:
                    pass
        s.tool_dead_count = dead_count
        if s.tool_total_count > 0:
            s.tool_dead_ratio = dead_count / s.tool_total_count

    # ── Code Health ─────────────────────────────────────────────────

    def _collect_code_health(self, s: MetricsSnapshot) -> None:
        """Collect codebase statistics."""
        tao_dir = self.base_dir / "tain_agent"
        if not tao_dir.exists():
            return

        total_lines = 0
        py_count = 0
        test_count = 0
        all_imports = []

        for py_file in tao_dir.rglob("*.py"):
            if py_file.name.startswith("_"):
                continue
            py_count += 1
            if "test" in py_file.name.lower() or "test" in str(py_file.parent).lower():
                test_count += 1
            try:
                lines = py_file.read_text(encoding="utf-8").split("\n")
                total_lines += len(lines)
                # Collect imports for duplication estimate
                for line in lines:
                    if line.strip().startswith("import ") or line.strip().startswith("from "):
                        all_imports.append(line.strip())
            except Exception:
                pass

        s.code_total_lines = total_lines
        s.code_py_files = py_count
        s.code_test_files = test_count

        # Simple duplication estimate: repeated import lines ratio
        if all_imports:
            unique_imports = len(set(all_imports))
            s.code_duplication_estimate = 1.0 - (unique_imports / len(all_imports))

    # ── Personality ─────────────────────────────────────────────────

    def _collect_personality(self, s: MetricsSnapshot) -> None:
        """Collect personality development metrics."""
        if self.personality:
            try:
                intro = self.personality.introspect()
                self._extract_personality_from_data(s, intro.get("traits", {}))
                return
            except (AttributeError, Exception):
                pass

        # Fallback: read from disk
        disk_path = Path("agent_workspace/state/personality.json")
        if disk_path.exists():
            try:
                data = json.loads(disk_path.read_text(encoding="utf-8"))
                self._extract_personality_from_data(s, data.get("traits", {}))
                return
            except (json.JSONDecodeError, Exception):
                pass

    def _extract_personality_from_data(self, s: MetricsSnapshot, traits: dict) -> None:
        """Extract personality metrics from traits dict (same logic for instance/disk)."""
        developed = sum(1 for cat, tlist in traits.items() if len(tlist) > 0)
        s.personality_dimensions_developed = developed
        s.personality_total_dimensions = len(traits) if traits else 7

        all_traits = []
        for tlist in traits.values():
            all_traits.extend(tlist)
        s.personality_total_traits = len(all_traits)
        s.personality_high_confidence_traits = sum(
            1 for t in all_traits if t.get("confidence", 0) >= 0.7
        )

    # ── Evolution Efficiency ────────────────────────────────────────

    def _collect_evolution_efficiency(self, s: MetricsSnapshot) -> None:
        """Collect improvement loop statistics."""
        if not self.improvement_loop:
            return

        try:
            state = self.improvement_loop.export_state()
            s.evolution_total_cycles = state.get("cycle_count", 0)
            s.evolution_improvements_made = state.get("improvements_this_session", 0)
            if s.evolution_total_cycles > 0:
                s.evolution_improvement_rate = s.evolution_improvements_made / s.evolution_total_cycles
            s.evolution_streak_no_improvement = getattr(
                self.improvement_loop, '_no_improvement_streak', 0
            )
        except (AttributeError, Exception):
            pass

    # ── Git Stats ───────────────────────────────────────────────────

    def _collect_git_stats(self, s: MetricsSnapshot) -> None:
        """Collect git history statistics."""
        try:
            # Commit count
            result = subprocess.run(
                ["git", "rev-list", "--count", "HEAD"],
                capture_output=True, text=True, timeout=10,
                cwd=str(self.base_dir),
            )
            if result.returncode == 0:
                s.git_commit_count = int(result.stdout.strip())

            # Days since last commit
            result = subprocess.run(
                ["git", "log", "-1", "--format=%aI"],
                capture_output=True, text=True, timeout=10,
                cwd=str(self.base_dir),
            )
            if result.returncode == 0:
                last_commit_str = result.stdout.strip()
                if last_commit_str:
                    last_commit = datetime.fromisoformat(last_commit_str)
                    s.git_days_since_last_commit = (now() - last_commit).total_seconds() / 86400
        except (FileNotFoundError, subprocess.TimeoutExpired, Exception):
            pass


# ─── Snapshot Persistence ──────────────────────────────────────────────

def _project_root() -> Path:
    """Find the project root by looking for config.yaml or the tain_agent package."""
    # Strategy: this file is at tain_agent/tools/forged/evolution_metrics.py
    # Project root is 3 levels up
    candidates = [
        Path(__file__).resolve().parent.parent.parent.parent,
        Path(".").resolve(),
    ]
    for c in candidates:
        if (c / "config.yaml").exists():
            return c
    return candidates[0]

def _snapshots_dir(base_dir: str = None) -> Path:
    if base_dir is None:
        base_dir = str(_project_root())
    d = Path(base_dir) / "tain_agent" / "state" / "metrics_snapshots"
    d.mkdir(parents=True, exist_ok=True)
    return d


def save_snapshot(snapshot: MetricsSnapshot, base_dir: str = None) -> Path:
    """Persist a metrics snapshot to disk for later comparison."""
    path = _snapshots_dir(base_dir) / f"metrics_{snapshot.version}.json"
    path.write_text(json.dumps(snapshot.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def load_snapshot(version: str, base_dir: str = None) -> Optional[MetricsSnapshot]:
    """Load a previously saved metrics snapshot."""
    path = _snapshots_dir(base_dir) / f"metrics_{version}.json"
    if not path.exists():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    return MetricsSnapshot.from_dict(data)


def list_snapshots(base_dir: str = None) -> list[str]:
    """List all saved snapshot versions."""
    d = _snapshots_dir(base_dir)
    if not d.exists():
        return []
    versions = []
    for f in sorted(d.glob("metrics_*.json")):
        m = re.match(r"metrics_(.+)\.json", f.name)
        if m:
            versions.append(m.group(1))
    return versions


# ─── Degradation Alerts ────────────────────────────────────────────────

def check_degradation(current: MetricsSnapshot, previous: MetricsSnapshot,
                      alert_threshold: float = 0.15) -> list[dict]:
    """Check for degradation between two snapshots.

    Returns a list of alert dicts for metrics that have declined
    beyond the alert threshold.
    """
    comp = MetricsComparison(previous, current)
    degradations = comp.get_degradations()

    alerts = []
    for d in degradations:
        if abs(d["change_pct"]) >= alert_threshold * 100:
            alerts.append({
                "alert": "degradation",
                "label": d["label"],
                "metric_key": d["metric"],
                "from": d["from"],
                "to": d["to"],
                "change_pct": d["change_pct"],
                "severity": d["severity"],
                "suggestion": _get_suggestion(d["metric"]),
            })

    return alerts


def _get_suggestion(metric_key: str) -> str:
    suggestions = {
        "knowledge_fresh_ratio": "运行 knowledge_freshness 检查并更新过期知识",
        "knowledge_isolated_ratio": "运行 knowledge_linker 连接孤立知识节点",
        "tool_success_rate": "检查失败的工具调用日志，修复问题工具",
        "tool_dead_ratio": "运行 tool_fitness 分析，考虑移除或更新死工具",
        "code_total_lines": "检查是否有冗余代码，运行 code_entropy 分析",
        "evolution_improvement_rate": "检查改进循环配置，降低 min_trigger_score",
        "evolution_streak_no_improvement": "连续无改进可能表明改进循环需要调整触发阈值",
        "personality_dimensions_developed": "使用 personality_introspect 反思并记录行为模式",
    }
    return suggestions.get(metric_key, "检查相关系统状态并考虑采取纠正行动")


# ─── Tool Entry Point ──────────────────────────────────────────────────

def collect(version: str = "", compare_with: str = "",
            agent_name: str = "") -> dict:
    """Main entry point for the evolution_metrics tool.

    Args:
        version: Current version string. Auto-detected if empty.
        compare_with: Previous version to compare against. If empty and a
                      prior snapshot exists, compares with the most recent.
        agent_name: Current agent name for workspace-scoped tool discovery.

    Returns:
        dict with snapshot, comparison (if applicable), and any alerts.
    """
    # Auto-detect version from config.yaml
    root = _project_root()
    if not version:
        try:
            import yaml
            cfg = yaml.safe_load((root / "config.yaml").read_text(encoding="utf-8")) or {}
            version = cfg.get("agent", {}).get("version", "0.0.0")
        except Exception:
            version = "0.0.0"

    # Collect current metrics (use project root, not CWD)
    collector = MetricsCollector(base_dir=str(root), agent_name=agent_name)
    snapshot = collector.collect(version=version)

    result = {
        "status": "ok",
        "snapshot": snapshot.to_dict(),
    }

    # Save snapshot
    saved_path = save_snapshot(snapshot)
    result["snapshot_saved"] = str(saved_path)

    # Compare with previous version if available
    if not compare_with:
        # Auto-find previous snapshot
        all_versions = list_snapshots()
        # Filter out current version
        others = [v for v in all_versions if v != version]
        if others:
            compare_with = others[-1]  # most recent

    if compare_with:
        prev = load_snapshot(compare_with)
        if prev:
            comparison = MetricsComparison(prev, snapshot)
            result["comparison"] = comparison.to_dict()
            result["dashboard"] = comparison.format_dashboard()
            result["degradations"] = comparison.get_degradations()

            # Check for alerts
            alerts = check_degradation(snapshot, prev)
            if alerts:
                result["alerts"] = alerts

    # Check for zero-improvement situation (connected to passive maintenance)
    if snapshot.evolution_total_cycles > 0 and snapshot.evolution_improvement_rate == 0.0:
        result.setdefault("alerts", []).append({
            "alert": "stagnation",
            "label": "改进率",
            "metric_key": "evolution_improvement_rate",
            "severity": "warning",
            "suggestion": "改进率为零。考虑降低 min_trigger_score 或检查驱动系统探索分数。",
        })

    return result


def main(action: str = "collect", version: str = "", compare_with: str = "",
         agent_name: str = "") -> str:
    """Forged tool entry point."""
    if action == "collect":
        result = collect(version=version, compare_with=compare_with,
                        agent_name=agent_name)
    elif action == "list":
        versions = list_snapshots()
        result = {"status": "ok", "snapshots": versions}
    elif action == "check":
        result = collect(version=version, compare_with=compare_with,
                        agent_name=agent_name)
        # Focus on alerts
        alerts = result.get("alerts", [])
        degradations = result.get("degradations", [])
        result = {
            "status": "ok",
            "alerts": alerts,
            "degradation_count": len(degradations),
            "healthy": len(alerts) == 0,
        }
    else:
        result = {"status": "error", "message": f"Unknown action: {action}. Use collect/list/check."}

    return json.dumps(result, ensure_ascii=False, indent=2)
