# Fix Plan: Code Review Findings for release/0.5.1

**Date:** 2026-06-09
**Source:** `docs/report/code-review-release-0.5.1.md`
**Scope:** Fix 8 findings (4 critical + 4 high) across 3 files

---

## Changes

### Unit 1: `tain_agent/core/cognitive_loop.py`

#### Fix 1 — Inverted adaptive pressure direction (#1)

- **Location:** `_get_effective_pressures`, lines 164-166
- **Change:** Swap the adjustment direction during act drought:
  - `act = max(0.05, act - rate)` → `act = min(0.95, act + rate)`
  - `reflect = min(0.95, reflect + rate)` → `reflect = max(0.05, reflect - rate)`
- **Rationale:** An act drought means the agent is over-reflecting. The adjustment should increase act pressure and decrease reflect ratio to break the drought, not reinforce it.

### Unit 2: `tain_agent/tools/forge.py`

#### Fix 2 — Unguarded `del` on forge update (#3)

- **Location:** `_forge_register`, line 363
- **Change:** `del self._forged_tools[name]` → `self._forged_tools.pop(name, None)`
- **Rationale:** If `_forged_tools` and registry are out of sync, `del` raises an unhandled `KeyError`. `pop(name, None)` safely removes the key if present.

### Unit 3: `tain_agent/evolution/quality_gate.py`

#### Fix 3 — H4 agent_name omission (#8)

- **Location:** `_h4_safety_boundary`, line 390
- **Change:** `_workspace_dir()` → `_workspace_dir(agent_name)`
- **Rationale:** Without `agent_name`, only the global workspace log is checked. Pass `agent_name` so agent-specific `decision_log.json` files are also scanned. `_workspace_dir` has built-in fallback to global root.

#### Fix 4 — H2 sys.modules pollution (#4)

- **Location:** `_h2_tool_loadability`, lines 291-298
- **Change:**
  1. Before `sys.modules[name] = mod`, check if `name` already in `sys.modules` — if so, raise `ImportError`
  2. Wrap `exec_module` in `try/except`; on failure, `del sys.modules[name]` then re-raise
- **Rationale:** Prevents partial module pollution and shadowing of stdlib packages.

#### Fix 5 — S7 workspace fallback (#5)

- **Location:** `_s7_drive_integrity`, lines 873-875
- **Change:** Insert a `_workspace_dir()` (no agent_name) fallback between the agent-specific path and the framework built-in path.
- **Rationale:** Adds consistency with H4/H6/H7 which all have a global workspace fallback.

#### Fix 6 — S9 dedup trend: replace Markdown regex with structured snapshots (#2 + #6)

- **Location:** `_s9_dedup_trend`, lines 1005-1039
- **Change:**
  1. Replace Markdown regex parsing with reading `state/metrics_snapshots/metrics_*.json` (same source as S7)
  2. Extract `tool_efficacy.total_tools` from the last 2 snapshots
  3. Compute two deltas: `trend_delta = latest_count - prev_count` (milestone trend) and `current_delta = current_count - latest_count` (recent change)
  4. Score based on both signals
- **Rationale:** Snapshots are already written by `EvolutionReporter._build_metrics_section()` via `save_snapshot()`. This eliminates fragile regex screen-scraping and correctly uses `prev_count`.

#### Fix 7 — S2 cross-layer dependency (#7)

- **Location:** `_s2_knowledge_coverage`, lines 660-667
- **Change:**
  1. Add `import logging` and `logger = logging.getLogger(__name__)` at module level
  2. Move `from tain_agent.plugins.knowledge.lifecycle import get_referenced_files` to module top, in a `try/except ImportError` that sets `get_referenced_files = None` and logs a warning
  3. Replace the in-function `try/except ImportError: pass` with a guard that checks `get_referenced_files is not None` and wraps the call in `try/except Exception` with logging
- **Rationale:** Eliminates silent degradation and hidden cross-layer dependency. Import failure is now visible in logs.

---

## Verification

After all fixes are applied:

1. `python -c "from tain_agent.core.cognitive_loop import CognitiveLoop; print('OK')"` — syntax/symbol check
2. `python -c "from tain_agent.tools.forge import Forge; print('OK')"` — syntax/symbol check
3. `python -c "from tain_agent.evolution.quality_gate import *; print('OK')"` — syntax/symbol check
4. Run existing tests: `python -m pytest tests/test_quality_gate.py tests/test_forge_integration.py tests/test_knowledge_plugin.py -v`
