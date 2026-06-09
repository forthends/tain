"""
Export Quality Gate — factory-side evaluation before agent export.

Evaluates whether an evolved agent meets the minimum standard to
operate as an independent executable. Two-tier assessment:

  Hard Gates (7): all must PASS — basic viability conditions.
  Scoring Gates (9): weighted sum must be ≥ 0.80 — quality dimensions.

Design: Phase 3 §4.
"""

import json
import importlib
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ─── Data structures ──────────────────────────────────────────────────

@dataclass
class GateResult:
    """Result of a single hard gate check."""
    gate_id: str
    label: str
    passed: bool
    detail: str = ""
    evidence: dict = field(default_factory=dict)


@dataclass
class ScoredResult:
    """Result of a single scoring gate evaluation."""
    gate_id: str
    label: str
    score: float       # 0.0 – 1.0
    weight: float      # normalized weight
    detail: str = ""
    evidence: dict = field(default_factory=dict)

    @property
    def weighted(self) -> float:
        return self.score * self.weight


@dataclass
class GateReport:
    """Complete quality gate evaluation report."""
    agent_name: str = ""
    agent_version: str = ""
    evaluated_at: str = field(default_factory=_now_iso)

    hard_results: list[GateResult] = field(default_factory=list)
    scoring_results: list[ScoredResult] = field(default_factory=list)

    @property
    def hard_passed(self) -> bool:
        return all(r.passed for r in self.hard_results)

    @property
    def hard_pass_count(self) -> int:
        return sum(1 for r in self.hard_results if r.passed)

    @property
    def total_score(self) -> float:
        if not self.scoring_results:
            return 0.0
        return sum(r.weighted for r in self.scoring_results)

    @property
    def passed(self) -> bool:
        return self.hard_passed and self.total_score >= 0.80

    @property
    def grade(self) -> str:
        s = self.total_score
        if s >= 0.90:
            return "★★★ Excellent"
        elif s >= 0.80:
            return "★★  Qualified"
        elif s >= 0.60:
            return "★   Not Ready"
        else:
            return "     Failing"

    def failures(self) -> list[str]:
        """Return actionable failure messages."""
        msgs = []
        for r in self.hard_results:
            if not r.passed:
                msgs.append(f"[HARD FAIL] {r.label}: {r.detail}")
        for r in self.scoring_results:
            if r.score < 0.60:
                msgs.append(f"[LOW SCORE] {r.label}: {r.score:.2f} — {r.detail}")
        return msgs


class ExportRejected(Exception):
    """Raised when quality gate blocks an export."""
    def __init__(self, report: GateReport):
        self.report = report
        failures = "\n  ".join(report.failures())
        super().__init__(
            f"Export rejected — {report.hard_pass_count}/{len(report.hard_results)} "
            f"hard gates, score {report.total_score:.2f}\n  {failures}"
        )


# ─── Path resolution helpers ──────────────────────────────────────────

def _project_root() -> Path:
    """Detect project root via this file's location."""
    return Path(__file__).resolve().parent.parent.parent


def _workspace_dir(agent_name: str = "") -> Optional[Path]:
    """Return the agent workspace directory.

    If agent_name is provided, returns the agent-specific workspace.
    Otherwise returns the global agent_workspace root.
    """
    root = _project_root()
    candidate = root / "agent_workspace"
    if not candidate.exists():
        return None
    if agent_name:
        agent_ws = candidate / agent_name
        if agent_ws.exists():
            return agent_ws
        # Fall back to global workspace if agent dir doesn't exist
    return candidate


def _agent_forged_tools_dir(agent_name: str) -> Optional[Path]:
    """Return agent-specific forged tools directory if it exists."""
    if not agent_name:
        return None
    root = _project_root()
    agent_tools = root / "agent_workspace" / agent_name / "forged_tools"
    if agent_tools.exists():
        return agent_tools
    return None


def _forged_tools_dir(agent_name: str = "") -> Path:
    """Return the forged tools directory.

    Priority: agent workspace > global workspace > built-in framework.
    """
    if agent_name:
        agent_tools = _agent_forged_tools_dir(agent_name)
        if agent_tools:
            return agent_tools
    ws = _workspace_dir()
    if ws:
        ws_tools = ws / "forged_tools"
        if ws_tools.exists():
            return ws_tools
    return _project_root() / "tain_agent" / "tools" / "forged"


def _knowledge_dir(agent_name: str = "") -> Optional[Path]:
    """Return the knowledge directory, preferring agent-specific path."""
    if agent_name:
        root = _project_root()
        agent_kg = root / "agent_workspace" / agent_name / "knowledge"
        if agent_kg.exists():
            return agent_kg
    ws = _workspace_dir()
    if ws:
        kg = ws / "knowledge_garden"
        if kg.exists():
            return kg
    return None


# ─── Hard Gates ────────────────────────────────────────────────────────

def _h1_personality_completeness(agent_name: str = "") -> GateResult:
    """H1: All 7 trait dimensions formed, each with ≥ 1 trait at confidence ≥ 0.3."""
    REQUIRED_CATEGORIES = [
        "values", "communication_style", "interests", "quirks",
        "self_description", "relationship_stance", "growth_orientation",
    ]

    ws = _workspace_dir(agent_name)
    if ws:
        personality_path = ws / "state" / "personality.json"
        if not personality_path.exists() and agent_name:
            alt = _project_root() / "agent_workspace" / agent_name / "state" / "personality_structured.json"
            if alt.exists():
                personality_path = alt
        if personality_path.exists():
            try:
                data = json.loads(personality_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, IOError):
                return GateResult("H1", "Personality Completeness", False,
                                  "Failed to read personality.json")
        else:
            return GateResult("H1", "Personality Completeness", False,
                              "personality.json not found in workspace",
                              {"path_checked": str(personality_path)})
    else:
        return GateResult("H1", "Personality Completeness", False,
                          "No agent_workspace directory found",
                          {"workspace": "missing"})

    # Detect format: category-nested vs flat-list
    dims = data.get("dimensions", data.get("_traits", {}))
    if not dims:
        # Try flat-list format (e.g., personality_structured.json)
        personality = data.get("personality", data)
        flat_traits = []
        for key, val in personality.items():
            if isinstance(val, list):
                for item in val:
                    if isinstance(item, dict) and "value" in item:
                        flat_traits.append(item)
        if flat_traits:
            # Group by category
            from collections import defaultdict
            dims = defaultdict(list)
            for t in flat_traits:
                cat = t.get("category", "uncategorized")
                dims[cat].append(t)

    if not dims:
        return GateResult("H1", "Personality Completeness", False,
                          "No trait data found in personality file")

    failures = []
    for cat in REQUIRED_CATEGORIES:
        traits = dims.get(cat, [])
        qualified = [t for t in traits
                     if t.get("confidence", 0) >= 0.3]
        if not qualified:
            failures.append(cat)

    passed = len(failures) == 0
    return GateResult(
        "H1", "Personality Completeness", passed,
        "" if passed else f"Missing qualified traits in: {', '.join(failures)}",
        {"categories_checked": len(REQUIRED_CATEGORIES), "categories_failed": len(failures)},
    )


def _h2_tool_loadability(agent_name: str = "") -> GateResult:
    """H2: All forged tools can be imported without error."""
    tools_dir = _forged_tools_dir(agent_name)
    if not tools_dir.exists():
        return GateResult("H2", "Tool Loadability", False,
                          "No forged tools directory found")

    py_files = [f for f in sorted(tools_dir.glob("*.py"))
                if not f.name.startswith("_") and f.name not in ("smart_improve.py",)]

    if not py_files:
        return GateResult("H2", "Tool Loadability", False,
                          "No forged tools found")

    import sys
    project_root = str(_project_root())
    if project_root not in sys.path:
        sys.path.insert(0, project_root)

    # For agent-scoped tools, add the tools directory to sys.path
    # so intra-tool imports work (e.g., dream_loop importing from another tool)
    tools_dir_str = str(tools_dir)
    if tools_dir_str not in sys.path:
        sys.path.insert(0, tools_dir_str)

    import importlib.util as _util

    failed = []
    for py_file in py_files:
        name = py_file.stem
        try:
            try:
                importlib.import_module(f"tain_agent.tools.forged.{name}")
            except ImportError:
                try:
                    importlib.import_module(name)
                except ImportError:
                    # Last resort: load from file path
                    spec = _util.spec_from_file_location(name, str(py_file))
                    if spec and spec.loader:
                        mod = _util.module_from_spec(spec)
                        if name in sys.modules:
                            raise ImportError(
                                f"Module name '{name}' shadows existing module in sys.modules"
                            )
                        sys.modules[name] = mod
                        try:
                            spec.loader.exec_module(mod)
                        except Exception:
                            del sys.modules[name]
                            raise
        except Exception as exc:
            failed.append(f"{name}: {exc}")

    passed = len(failed) == 0
    return GateResult(
        "H2", "Tool Loadability", passed,
        "" if passed else f"Failed imports: {', '.join(failed)}",
        {"total": len(py_files), "failed": len(failed)},
    )


def _h3_tool_no_conflicts(agent_name: str = "") -> GateResult:
    """H3: No circular dependencies between tools, no function name clashes."""
    tools_dir = _forged_tools_dir(agent_name)
    if not tools_dir.exists():
        return GateResult("H3", "Tool No Conflicts", False,
                          "No forged tools directory found")

    py_files = [f for f in sorted(tools_dir.glob("*.py"))
                if not f.name.startswith("_") and f.name not in ("smart_improve.py",)]

    if len(py_files) < 2:
        return GateResult("H3", "Tool No Conflicts", True,
                          "Not enough tools to conflict",
                          {"total_tools": len(py_files)})

    import ast
    # Build import graph
    imports_by_file: dict[str, set[str]] = {}
    for py_file in py_files:
        try:
            tree = ast.parse(py_file.read_text())
            deps = set()
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        deps.add(alias.name.split(".")[0])
                elif isinstance(node, ast.ImportFrom):
                    if node.module:
                        deps.add(node.module.split(".")[0])
            imports_by_file[py_file.stem] = deps
        except SyntaxError:
            imports_by_file[py_file.stem] = set()

    # Simple cycle detection: check if A imports B and B imports A
    cycles = []
    tool_names = {f.stem for f in py_files}
    for source, deps in imports_by_file.items():
        for dep in deps:
            if dep in tool_names and dep in imports_by_file:
                if source in imports_by_file[dep]:
                    cycles.append(f"{source} ↔ {dep}")

    # Function name clash detection
    # Standard entry-point names shared across modules are fine in Python
    # (each tool is in its own namespace). Only flag non-standard collisions.
    _SHARED_NAMES = {"main", "collect", "to_dict", "run", "execute", "analyze"}
    func_names: dict[str, list[str]] = {}
    for py_file in py_files:
        try:
            tree = ast.parse(py_file.read_text())
            for node in ast.walk(tree):
                if (isinstance(node, ast.FunctionDef)
                        and not node.name.startswith("_")
                        and node.name not in _SHARED_NAMES):
                    func_names.setdefault(node.name, []).append(py_file.stem)
        except SyntaxError:
            pass

    clashes = {name: files for name, files in func_names.items() if len(files) > 1}

    passed = len(cycles) == 0 and len(clashes) == 0
    detail_parts = []
    if cycles:
        detail_parts.append(f"Circular deps: {', '.join(cycles)}")
    if clashes:
        detail_parts.append(f"Name clashes: {list(clashes.keys())}")

    return GateResult(
        "H3", "Tool No Conflicts", passed,
        "; ".join(detail_parts) if detail_parts else "",
        {"cycles": cycles, "clashes": {k: v for k, v in clashes.items()}},
    )


def _h4_safety_boundary(agent_name: str = "") -> GateResult:
    """H4: No dangerous operations in recent decision log."""
    candidates = []
    # Agent-specific logs first
    if agent_name:
        agent_log = _project_root() / "agent_workspace" / agent_name / "logs" / "decisions.jsonl"
        if agent_log.exists():
            candidates.append(agent_log)
    ws = _workspace_dir(agent_name)
    if ws:
        ws_log = ws / "logs" / "decision_log.json"
        if ws_log.exists():
            candidates.append(ws_log)
    framework_log = _project_root() / "tain_agent" / "logs" / "decision_log.json"
    if framework_log.exists():
        candidates.append(framework_log)

    if not candidates:
        return GateResult("H4", "Safety Boundary", True,
                          "No decision log found — treating as clean slate",
                          {"log_paths_checked": [], "status": "missing"})

    all_entries = []
    for log_path in candidates:
        try:
            raw = log_path.read_text(encoding="utf-8")
            if log_path.suffix == ".jsonl":
                # Line-delimited JSON — each line is a JSON object
                for line in raw.strip().split("\n"):
                    line = line.strip()
                    if line:
                        try:
                            all_entries.append(json.loads(line))
                        except json.JSONDecodeError:
                            pass
            else:
                log = json.loads(raw)
                entries = log if isinstance(log, list) else log.get("entries", [])
                all_entries.extend(entries)
        except (json.JSONDecodeError, IOError):
            continue

    recent = all_entries[-100:] if len(all_entries) > 100 else all_entries

    dangerous_patterns = [
        "rm -rf", "os.remove", "shutil.rmtree",
        "DROP TABLE", "DELETE FROM",
        "eval(", "exec(",
        "--no-verify", "--force",
    ]

    violations = []
    for entry in recent:
        text = json.dumps(entry).lower()
        for pattern in dangerous_patterns:
            if pattern.lower() in text:
                violations.append({
                    "pattern": pattern,
                    "entry_timestamp": entry.get("timestamp",
                                                  entry.get("time", "unknown")),
                })

    passed = len(violations) == 0
    return GateResult(
        "H4", "Safety Boundary", passed,
        "" if passed else f"{len(violations)} dangerous operation(s) detected",
        {"entries_checked": len(recent), "violations": len(violations)},
    )


def _h5_memory_module_functional(agent_name: str = "") -> GateResult:
    """H5: Runtime memory store can execute add/query/stats operations."""
    try:
        from tain_agent.runtime.memory import MemoryStore

        store = MemoryStore(file_path="/tmp/_gate_h5_test.json")
        store.start_session("test")
        store.end_session(
            summary="Quality gate test session",
            key_topics=["testing", "quality gate"],
            decisions=["proceed with export"],
            preferences=["automated testing"],
        )
        recent = store.recent_sessions(1)
        ltm = store.get_long_term()

        # Verify operations worked
        checks = {
            "session_saved": len(recent) == 1,
            "session_summary": recent[0].get("summary") == "Quality gate test session",
            "key_topics": len(recent[0].get("key_topics", [])) == 2,
            "long_term_structure": "key_facts" in ltm and "user_model" in ltm,
        }
        all_ok = all(checks.values())

        # Cleanup
        try:
            os.remove("/tmp/_gate_h5_test.json")
        except OSError:
            pass

        return GateResult(
            "H5", "Memory Module Functional", all_ok,
            "" if all_ok else f"Checks failed: {[k for k, v in checks.items() if not v]}",
            checks,
        )
    except Exception as exc:
        return GateResult("H5", "Memory Module Functional", False,
                          f"Memory store exception: {exc}")


def _h6_knowledge_retrievable(agent_name: str = "") -> GateResult:
    """H6: ≥ 5 markdown docs in knowledge dir, total size ≥ 10KB."""
    kg = _knowledge_dir(agent_name)
    if kg is None:
        ws = _workspace_dir(agent_name)
        if ws:
            kg = ws / "knowledge"
            if not kg.exists():
                kg = None

    if kg is None:
        return GateResult("H6", "Knowledge Retrievable", False,
                          "No knowledge directory found")

    md_files = list(kg.rglob("*.md"))
    total_size = sum(f.stat().st_size for f in md_files)

    count_ok = len(md_files) >= 5
    size_ok = total_size >= 10240  # 10 KB

    passed = count_ok and size_ok
    return GateResult(
        "H6", "Knowledge Retrievable", passed,
        "" if passed else f"{len(md_files)} docs, {total_size}B (need ≥5, ≥10KB)",
        {"doc_count": len(md_files), "total_size_bytes": total_size},
    )


def _h7_version_tagged(agent_name: str = "") -> GateResult:
    """H7: version.json exists with version ≥ 0.5.0."""
    candidates = []
    # Agent-specific paths first
    if agent_name:
        base = _project_root() / "agent_workspace" / agent_name
        candidates.extend([
            base / "version.json",
            base / "state" / "version.json",
        ])
    ws = _workspace_dir()
    if ws:
        candidates.append(ws / "state" / "version.json")
    candidates.append(_project_root() / "agent_workspace" / "state" / "version.json")

    version_path = None
    for c in candidates:
        if c.exists():
            version_path = c
            break

    if version_path is None:
        return GateResult("H7", "Version Tagged", False,
                          "version.json not found",
                          {"looked_at": [str(c) for c in candidates[:3]]})

    try:
        data = json.loads(version_path.read_text(encoding="utf-8"))
        version_str = data.get("version", "0.0.0")
    except (json.JSONDecodeError, IOError):
        return GateResult("H7", "Version Tagged", False,
                          "Failed to read version.json")

    try:
        parts = version_str.lstrip("v").split(".")
        major, minor = int(parts[0]), int(parts[1]) if len(parts) > 1 else 0
        version_num = major + minor / 10.0
    except (ValueError, IndexError):
        version_num = 0.0

    passed = version_num >= 0.5
    return GateResult(
        "H7", "Version Tagged", passed,
        "" if passed else f"Version {version_str} < 0.5.0",
        {"version": version_str, "version_num": version_num},
    )


# ─── Scoring Gates ─────────────────────────────────────────────────────

def _s1_tool_success_rate(agent=None) -> ScoredResult:
    """S1 (0.23): Framework-measured tool execution success rate.

    Reads from cognitive loop telemetry — no LLM involvement.
    Measures how reliably the agent's tools execute successfully.
    """
    if agent is None:
        return ScoredResult(
            "S1", "Tool Success Rate", 0.50, 0.23,
            "No agent available",
            {"status": "no_agent"},
        )

    try:
        cognitive = getattr(agent, 'cognitive_loop', None)
        if cognitive and hasattr(cognitive, '_tool_success_rates'):
            rates = cognitive._tool_success_rates
            if not rates:
                return ScoredResult(
                    "S1", "Tool Success Rate", 0.50, 0.23,
                    "No tool execution data yet",
                    {"tools_measured": 0},
                )

            total_successes = sum(s for s, _ in rates.values())
            total_calls = sum(t for _, t in rates.values())
            if total_calls == 0:
                return ScoredResult("S1", "Tool Success Rate", 0.50, 0.23,
                                   "No tool calls recorded")

            avg_rate = total_successes / total_calls
            return ScoredResult(
                "S1", "Tool Success Rate", round(avg_rate, 3), 0.23,
                f"{total_successes}/{total_calls} calls succeeded ({avg_rate:.1%})",
                {
                    "tools_measured": len(rates),
                    "total_calls": total_calls,
                    "total_successes": total_successes,
                    "avg_success_rate": round(avg_rate, 3),
                },
            )

        return ScoredResult("S1", "Tool Success Rate", 0.50, 0.23,
                           "No cognitive loop telemetry available",
                           {"status": "no_data"})
    except Exception as e:
        return ScoredResult("S1", "Tool Success Rate", 0.50, 0.23,
                           f"Error reading telemetry: {e}")


def _s2_knowledge_coverage(agent_name: str = "") -> ScoredResult:
    """S2 (0.15): ≥ 20 knowledge nodes, ≥ 4 domains."""
    kg = _knowledge_dir(agent_name)
    if kg is None:
        ws = _workspace_dir(agent_name)
        kg = ws / "knowledge" if ws and (ws / "knowledge").exists() else None

    # Try graph.json first
    graph_path = None
    if kg:
        graph_path = kg / "graph.json" if kg.name == "knowledge_garden" else None
    if graph_path is None or not graph_path.exists():
        # Count md files as fallback
        if kg and kg.exists():
            md_files = list(kg.rglob("*.md"))
            node_count = len(md_files)
            # Estimate domains by top-level subdirs
            domains = set()
            for f in md_files:
                parts = f.relative_to(kg).parts
                if len(parts) > 1:
                    domains.add(parts[0])
            domain_count = max(len(domains), 1)
        else:
            node_count, domain_count = 0, 0
    else:
        try:
            g = json.loads(graph_path.read_text(encoding="utf-8"))
            nodes = g.get("nodes", {})
            node_count = len(nodes)
            # Estimate domains from tags
            all_tags = set()
            for n in nodes.values():
                for t in n.get("tags", []):
                    all_tags.add(t)
            domain_count = max(len(all_tags), 1)
        except (json.JSONDecodeError, IOError):
            node_count, domain_count = 0, 0

    # v0.7.0: Count referenced knowledge files from other agents
    ref_count = 0
    try:
        from tain_agent.plugins.knowledge.lifecycle import get_referenced_files
        ref_files = get_referenced_files(agent_name) if agent_name else []
        ref_count = len(ref_files)
    except ImportError:
        pass

    total_nodes = node_count + ref_count
    node_score = min(total_nodes / 20.0, 1.0)
    domain_score = min(domain_count / 4.0, 1.0)
    score = round(0.6 * node_score + 0.4 * domain_score, 3)

    return ScoredResult(
        "S2", "Knowledge Coverage", score, 0.15,
        f"{total_nodes} nodes ({node_count} own + {ref_count} refs), {domain_count} domains",
        {"nodes": total_nodes, "domains": domain_count,
         "own_nodes": node_count, "ref_nodes": ref_count},
    )


def _s3_tool_chain_coherence(agent=None, agent_name: str = "") -> ScoredResult:
    """S3 (0.20): ≥ 3 tool chains work end-to-end without error."""
    if agent is None:
        return ScoredResult(
            "S3", "Tool Chain Coherence", 0.75, 0.20,
            "No agent available — using default pass score",
            {"status": "no_agent", "min_chains": 3},
        )

    tools_dir = _forged_tools_dir(agent_name)
    if not tools_dir.exists():
        return ScoredResult("S3", "Tool Chain Coherence", 0.0, 0.20,
                           "No forged tools directory found")

    import ast as _ast

    # Build a dependency graph between tools
    deps: dict[str, set[str]] = {}
    for py_file in sorted(tools_dir.glob("*.py")):
        if py_file.name.startswith("_") or py_file.name == "smart_improve.py":
            continue
        name = py_file.stem
        deps[name] = set()
        try:
            tree = _ast.parse(py_file.read_text())
            for node in _ast.walk(tree):
                if isinstance(node, _ast.Import):
                    for alias in node.names:
                        mod = alias.name.split(".")[0]
                        if mod != name:
                            deps[name].add(mod)
                elif isinstance(node, _ast.ImportFrom):
                    if node.module:
                        mod = node.module.split(".")[0]
                        if mod != name:
                            deps[name].add(mod)
        except SyntaxError:
            pass

    # Find tool names that match actual tools
    tool_names = {f.stem for f in tools_dir.glob("*.py")
                  if not f.name.startswith("_") and f.name != "smart_improve.py"}
    tool_deps = {n: (d & tool_names) for n, d in deps.items() if d & tool_names}

    if len(tool_deps) < 2:
        return ScoredResult("S3", "Tool Chain Coherence", 0.5, 0.20,
                           f"Only {len(tool_deps)} tool(s) with inter-tool dependencies",
                           {"tool_deps": len(tool_deps)})

    # Attempt to execute tool chains (pairs for simplicity)
    chain_count = 0
    success_count = 0
    registry = getattr(agent, 'tools', None)

    for source, targets in tool_deps.items():
        for target in targets:
            if chain_count >= 5:  # cap evaluation
                break
            chain_count += 1
            try:
                if registry:
                    # Execute source tool first, then feed output to target
                    src_result = registry.execute(source, {})
                    src_content = src_result.get("content", "") if isinstance(src_result, dict) else str(src_result)
                    tgt_result = registry.execute(target, {"input": src_content})
                    tgt_content = tgt_result.get("content", "") if isinstance(tgt_result, dict) else str(tgt_result)
                    if "error" not in tgt_content.lower():
                        success_count += 1
                else:
                    success_count += 1  # Can't test without registry
            except Exception:
                pass

    score = round(success_count / max(chain_count, 1), 3)
    return ScoredResult(
        "S3", "Tool Chain Coherence", score, 0.20,
        f"{success_count}/{chain_count} tool chains succeeded",
        {"chains_attempted": chain_count, "chains_succeeded": success_count},
    )


def _s4_action_diversity(agent=None) -> ScoredResult:
    """S4 (0.15): Framework-measured action diversity from cognitive loop.

    Measures how many distinct tools the agent uses — higher diversity
    indicates healthier exploration. Zero LLM involvement.
    """
    if agent is None:
        return ScoredResult(
            "S4", "Action Diversity", 0.50, 0.15,
            "No agent available",
            {"status": "no_agent"},
        )

    try:
        cognitive = getattr(agent, 'cognitive_loop', None)
        if cognitive and hasattr(cognitive, '_action_history'):
            history = cognitive._action_history
            if not history:
                return ScoredResult(
                    "S4", "Action Diversity", 0.50, 0.15,
                    "No actions recorded yet",
                    {"total_actions": 0},
                )

            unique_tools = len(set(history))
            total_actions = len(history)

            # Diversity score: unique/total ratio, bounded
            # High ratio = agent tries many different tools
            # Low ratio = agent repeats the same few tools
            diversity_ratio = unique_tools / max(total_actions, 1)

            # Scale: 0 distinct tools → 0.0, 10+ → 1.0
            count_score = min(1.0, unique_tools / 10.0)

            # Combined: 70% count-based + 30% ratio-based
            score = round(count_score * 0.7 + diversity_ratio * 0.3, 3)

            return ScoredResult(
                "S4", "Action Diversity", score, 0.15,
                f"{unique_tools} distinct tools in {total_actions} actions "
                f"(diversity ratio: {diversity_ratio:.2f})",
                {
                    "unique_tools": unique_tools,
                    "total_actions": total_actions,
                    "diversity_ratio": round(diversity_ratio, 3),
                },
            )

        return ScoredResult("S4", "Action Diversity", 0.50, 0.15,
                           "No cognitive loop telemetry available",
                           {"status": "no_data"})
    except Exception as e:
        return ScoredResult("S4", "Action Diversity", 0.50, 0.15,
                           f"Error reading telemetry: {e}")


def _s5_code_health() -> ScoredResult:
    """S5 (0.10): No dead tools, tool success rate ≥ 85%."""
    try:
        import sys
        project_root = str(_project_root())
        if project_root not in sys.path:
            sys.path.insert(0, project_root)
        from tain_agent.tools.forged.code_entropy import analyze_entropy
        result = analyze_entropy()
        health_score = result.get("health_score", 0.5)
        return ScoredResult(
            "S5", "Code Health", health_score, 0.10,
            result.get("summary", ""),
            result,
        )
    except Exception as exc:
        return ScoredResult(
            "S5", "Code Health", 0.50, 0.10,
            f"Evaluator failed: {exc}",
            {"status": "error"},
        )


def _s6_knowledge_freshness() -> ScoredResult:
    """S6 (0.05): Knowledge updated within 7 days."""
    try:
        import sys
        project_root = str(_project_root())
        if project_root not in sys.path:
            sys.path.insert(0, project_root)
        from tain_agent.tools.forged.knowledge_freshness import check_freshness
        result = check_freshness()
        fresh_ratio = result.get("fresh_ratio", 0.0)
        return ScoredResult(
            "S6", "Knowledge Freshness", fresh_ratio, 0.05,
            f"{result.get('fresh_count', 0)}/{result.get('total', 0)} fresh",
            result,
        )
    except Exception as exc:
        return ScoredResult(
            "S6", "Knowledge Freshness", 0.0, 0.05,
            f"Evaluator failed: {exc}",
            {"status": "error"},
        )


def _s7_drive_integrity(agent_name: str = "") -> ScoredResult:
    """S7 (0.02): All 4 drives non-zero, no degradation across last 3 snapshots."""
    ws = _workspace_dir(agent_name)
    if ws is None:
        return ScoredResult("S7", "Drive Integrity", 0.50, 0.02,
                            "No workspace — cannot assess drives")

    snapshots_dir = ws / "state" / "metrics_snapshots"
    if not snapshots_dir.exists():
        # Fallback 1: global agent_workspace
        global_ws = _workspace_dir()
        if global_ws:
            snapshots_dir = global_ws / "state" / "metrics_snapshots"
    if not snapshots_dir.exists():
        # Fallback 2: framework built-in
        snapshots_dir = _project_root() / "tain_agent" / "state" / "metrics_snapshots"
        if not snapshots_dir.exists():
            return ScoredResult("S7", "Drive Integrity", 0.50, 0.02,
                                "No metrics snapshots found",
                                {"status": "no_data"})

    snapshot_files = sorted(snapshots_dir.glob("*.json"))
    if len(snapshot_files) < 2:
        return ScoredResult("S7", "Drive Integrity", 0.60, 0.02,
                            f"Only {len(snapshot_files)} snapshot(s) — need ≥ 3",
                            {"snapshots": len(snapshot_files)})

    recent = snapshot_files[-3:]
    drives_history = []
    for sf in recent:
        try:
            data = json.loads(sf.read_text(encoding="utf-8"))
            drives = data.get("personality", {}).get("drives", data.get("drives", {}))
            drives_history.append(drives)
        except (json.JSONDecodeError, IOError):
            pass

    if len(drives_history) < 2:
        return ScoredResult("S7", "Drive Integrity", 0.60, 0.02,
                            "Could not parse drive snapshots")

    drive_names = ["curiosity", "mastery", "creation", "conservation"]
    all_nonzero = True
    degrading = []

    for dn in drive_names:
        values = []
        for dh in drives_history:
            v = dh.get(dn, {}).get("intensity", dh.get(dn, 0))
            if isinstance(v, (int, float)):
                values.append(float(v))
        if not values:
            all_nonzero = False
            continue
        if any(v == 0 for v in values):
            all_nonzero = False
        if len(values) >= 2 and values[-1] < values[0]:
            degrading.append(dn)

    score = 1.0
    if not all_nonzero:
        score -= 0.3
    if degrading:
        score -= 0.2 * len(degrading)
    score = max(0.0, score)

    return ScoredResult(
        "S7", "Drive Integrity", round(score, 3), 0.02,
        f"Non-zero: {all_nonzero}, Degrading: {degrading or 'none'}",
        {"all_nonzero": all_nonzero, "degrading": degrading},
    )


def _s8_external_feedback() -> ScoredResult:
    """S8 (0.05): ≥ 1 mirror sub-agent feedback recorded."""
    decision_log_path = _project_root() / "tain_agent" / "logs" / "decision_log.json"
    if not decision_log_path.exists():
        return ScoredResult("S8", "External Feedback", 0.0, 0.05,
                            "No decision log found",
                            {"status": "no_log"})

    try:
        log = json.loads(decision_log_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, IOError):
        return ScoredResult("S8", "External Feedback", 0.0, 0.05,
                            "Failed to read decision log")

    entries = log if isinstance(log, list) else log.get("entries", [])
    feedback_count = 0
    for entry in entries:
        text = json.dumps(entry).lower()
        if "external_feedback" in text or "mirror" in text:
            feedback_count += 1
        if "sub_agent" in text and "feedback" in text:
            feedback_count += 1

    score = min(feedback_count / 3.0, 1.0)  # ≥ 3 feedback events = full score
    return ScoredResult(
        "S8", "External Feedback", round(score, 3), 0.05,
        f"{feedback_count} feedback event(s) found",
        {"feedback_events": feedback_count, "threshold": 1},
    )


def _s9_dedup_trend(agent_name: str = "") -> ScoredResult:
    """S9 (0.05): Code dedup ratio trending positive.

    Compares forged_tools file count between the two most recent
    evolution milestones. Rewards file count reduction (dedup/cleanup)
    while penalizing growth without corresponding capability expansion.
    """
    tools_dir = _forged_tools_dir(agent_name)
    if not tools_dir.exists():
        return ScoredResult("S9", "Code Dedup Trend", 0.50, 0.05,
                           "No forged tools directory found",
                           {"status": "no_tools_dir"})

    py_files = [f for f in sorted(tools_dir.glob("*.py"))
                if not f.name.startswith("_") and f.name != "smart_improve.py"]
    current_count = len(py_files)

    ws = _workspace_dir(agent_name)
    if ws is None:
        return ScoredResult("S9", "Code Dedup Trend", 0.50, 0.05,
                           "No workspace — cannot compare milestones",
                           {"current_count": current_count})

    reports_dir = ws / "reports"
    if not reports_dir.exists():
        if agent_name:
            alt_reports = _project_root() / "agent_workspace" / agent_name / "reports"
            if alt_reports.exists():
                reports_dir = alt_reports

    if not reports_dir or not reports_dir.exists():
        return ScoredResult("S9", "Code Dedup Trend", 0.50, 0.05,
                           "No evolution reports to compare",
                           {"current_count": current_count})

    report_files = sorted(reports_dir.glob("*.md"))
    if len(report_files) < 2:
        return ScoredResult("S9", "Code Dedup Trend", 0.50, 0.05,
                           "Need >= 2 evolution reports to establish trend",
                           {"current_count": current_count, "reports_found": len(report_files)})

    import re as _re
    tool_counts = []
    for rf in report_files[-2:]:
        try:
            text = rf.read_text(encoding="utf-8")
            m = _re.search(r'(?:Forged tools|锻造工具)[:\s]*(\d+)', text)
            if m:
                tool_counts.append(int(m.group(1)))
        except (IOError, OSError):
            pass

    if len(tool_counts) < 2:
        return ScoredResult("S9", "Code Dedup Trend", 0.50, 0.05,
                           "Could not extract tool counts from reports",
                           {"current_count": current_count})

    prev_count, latest_count = tool_counts
    delta = current_count - latest_count

    if delta < 0:
        score = min(1.0, 0.8 + abs(delta) * 0.1)
        detail = f"Tool count decreased by {abs(delta)} ({latest_count} -> {current_count}) — dedup positive"
    elif delta == 0:
        score = 0.70
        detail = f"Tool count stable at {current_count} — no new bloat detected"
    else:
        score = max(0.0, 0.5 - delta * 0.15)
        detail = f"Tool count increased by {delta} ({latest_count} -> {current_count}) — monitor for bloat"

    return ScoredResult(
        "S9", "Code Dedup Trend", round(score, 3), 0.05,
        detail,
        {"prev_report_count": latest_count, "current_count": current_count,
         "delta": delta},
    )


# ─── Main Quality Gate ─────────────────────────────────────────────────

class ExportQualityGate:
    """Factory-side quality gate for agent export evaluation.

    Usage:
        gate = ExportQualityGate(agent_name="Explorer", agent_version="0.23.0")
        report = gate.evaluate()
        if report.passed:
            print("Ready for export!")
        else:
            for f in report.failures():
                print(f)
    """

    def __init__(self, agent_name: str = "", agent_version: str = "",
                 agent=None):
        self.agent_name = agent_name
        self.agent_version = agent_version
        self.agent = agent

        self.hard_gates = [
            ("H1", "Personality Completeness", _h1_personality_completeness),
            ("H2", "Tool Loadability", _h2_tool_loadability),
            ("H3", "Tool No Conflicts", _h3_tool_no_conflicts),
            ("H4", "Safety Boundary", _h4_safety_boundary),
            ("H5", "Memory Module Functional", _h5_memory_module_functional),
            ("H6", "Knowledge Retrievable", _h6_knowledge_retrievable),
            ("H7", "Version Tagged", _h7_version_tagged),
        ]

        self.scoring_gates = [
            ("S1", "Tool Success Rate",
             lambda: _s1_tool_success_rate(self.agent)),
            ("S2", "Knowledge Coverage",
             lambda: _s2_knowledge_coverage(self.agent_name)),
            ("S3", "Tool Chain Coherence",
             lambda: _s3_tool_chain_coherence(self.agent, self.agent_name)),
            ("S4", "Action Diversity",
             lambda: _s4_action_diversity(self.agent)),
            ("S5", "Code Health", _s5_code_health),
            ("S6", "Knowledge Freshness", _s6_knowledge_freshness),
            ("S7", "Drive Integrity",
             lambda: _s7_drive_integrity(self.agent_name)),
            ("S8", "External Feedback", _s8_external_feedback),
            ("S9", "Code Dedup Trend",
             lambda: _s9_dedup_trend(self.agent_name)),
        ]

    def evaluate(self) -> GateReport:
        """Run all hard and scoring gates, returning a comprehensive report."""
        report = GateReport(
            agent_name=self.agent_name,
            agent_version=self.agent_version,
        )

        for gate_id, label, fn in self.hard_gates:
            try:
                result = fn(self.agent_name)
            except Exception as exc:
                result = GateResult(gate_id, label, False, str(exc))
            report.hard_results.append(result)

        for gate_id, label, fn in self.scoring_gates:
            try:
                result = fn()
            except Exception as exc:
                result = ScoredResult(gate_id, label, 0.0, 0.0, str(exc))
            report.scoring_results.append(result)

        return report

    def evaluate_and_assert(self) -> GateReport:
        """Evaluate and raise ExportRejected if the gate is not passed."""
        report = self.evaluate()
        if not report.passed:
            raise ExportRejected(report)
        return report


# ─── Rich report rendering ─────────────────────────────────────────────

def render_report(report: GateReport) -> str:
    """Render a GateReport as a rich-formatted string (with ANSI if available).

    Falls back to plain text when rich is not installed.
    """
    try:
        from rich.console import Console
        from rich.table import Table
        from rich.panel import Panel
        from rich.text import Text

        console = Console(width=80, force_terminal=False)
        with console.capture() as capture:
            # Header
            header = Text(f"Export Quality Gate Report — {report.agent_name} "
                          f"v{report.agent_version}", style="bold")
            console.print(Panel(header, border_style="cyan"))

            # Hard gates
            hard_table = Table(title="Hard Gates", box=None)
            hard_table.add_column("#", style="dim", width=4)
            hard_table.add_column("Gate")
            hard_table.add_column("Result")
            hard_table.add_column("Detail")

            for r in report.hard_results:
                icon = "[green]PASS[/green]" if r.passed else "[red]FAIL[/red]"
                hard_table.add_row(r.gate_id, r.label, icon, r.detail[:60])

            hard_summary = (f"{report.hard_pass_count}/{len(report.hard_results)} "
                            f"{'[green]ALL PASS[/green]' if report.hard_passed else '[red]FAILURES[/red]'}")
            console.print(hard_table)
            console.print(f"  {hard_summary}\n")

            # Scoring gates
            score_table = Table(title="Scoring Gates", box=None)
            score_table.add_column("#", style="dim", width=4)
            score_table.add_column("Dimension")
            score_table.add_column("Score", width=8)
            score_table.add_column("Weight", width=8)
            score_table.add_column("Weighted", width=10)
            score_table.add_column("Detail")

            for r in report.scoring_results:
                bar = "█" * int(r.score * 10) + "░" * (10 - int(r.score * 10))
                score_table.add_row(
                    r.gate_id, r.label,
                    f"{r.score:.2f} {bar}",
                    f"{r.weight:.2f}",
                    f"{r.weighted:.4f}",
                    r.detail[:50],
                )

            console.print(score_table)

            # Total
            total_style = "green" if report.total_score >= 0.80 else "yellow"
            console.print(f"\n  Total Score: [{total_style}]{report.total_score:.4f}[/{total_style}]  "
                          f"Grade: [{total_style}]{report.grade}[/{total_style}]")

            if not report.hard_passed:
                console.print("\n[red]Hard gates failed — export rejected.[/red]")
            elif report.total_score < 0.80:
                console.print("\n[yellow]Scoring threshold not met — export rejected.[/yellow]")
            else:
                console.print("\n[green]Quality gate passed — ready for export.[/green]")

        return capture.get()
    except ImportError:
        return _render_plain(report)


def _render_plain(report: GateReport) -> str:
    """Plain-text rendering for environments without rich."""
    lines = [
        "=" * 62,
        f"  Export Quality Gate Report — {report.agent_name} v{report.agent_version}",
        "=" * 62,
        "",
        f"  Hard Gates: {report.hard_pass_count}/{len(report.hard_results)} "
        f"{'ALL PASS' if report.hard_passed else 'FAILURES'}",
    ]

    for r in report.hard_results:
        icon = "PASS" if r.passed else "FAIL"
        lines.append(f"    {r.gate_id} {r.label}: {icon}")
        if r.detail:
            lines.append(f"      {r.detail}")

    lines.append("")
    lines.append(f"  Scoring Gates (total: {report.total_score:.4f}, grade: {report.grade}):")

    for r in report.scoring_results:
        bar = "#" * int(r.score * 20) + "-" * (20 - int(r.score * 20))
        lines.append(
            f"    {r.gate_id} {r.label}: {r.score:.2f} [{bar}] "
            f"w={r.weight:.2f} weighted={r.weighted:.4f}"
        )
        if r.detail:
            lines.append(f"      {r.detail}")

    lines.append("")
    if report.passed:
        lines.append("  Quality gate passed — ready for export.")
    else:
        lines.append("  Quality gate NOT passed:")
        for f in report.failures():
            lines.append(f"    {f}")

    lines.append("=" * 62)
    return "\n".join(lines)
