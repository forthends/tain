# Code Review Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix 8 code review findings (4 critical + 4 high) across 3 files: cognitive_loop.py, forge.py, quality_gate.py

**Architecture:** Three independent fix units with no cross-file dependencies. Unit 1 (1 fix) + Unit 2 (1 fix) are single-line corrections. Unit 3 (6 fixes) spans multiple functions in quality_gate.py but each fix is self-contained within its own function.

**Tech Stack:** Python 3.x, no new dependencies

---

### Task 1: Fix inverted adaptive pressure direction (critical #1)

**Files:**
- Modify: `tain_agent/core/cognitive_loop.py:164-166`

- [ ] **Step 1: Apply the fix**

In `_get_effective_pressures`, swap the adjustment direction during act drought:

```python
# Old (lines 164-166):
                if act_ratio < threshold:
                    act = max(0.05, act - rate)
                    reflect = min(0.95, reflect + rate)

# New:
                if act_ratio < threshold:
                    act = min(0.95, act + rate)
                    reflect = max(0.05, reflect - rate)
```

- [ ] **Step 2: Verify syntax**

Run: `python -c "from tain_agent.core.cognitive_loop import CognitiveLoop; print('OK')"`
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add tain_agent/core/cognitive_loop.py
git commit -m "fix(cognitive): invert adaptive pressure to break act drought rather than reinforce it"
```

---

### Task 2: Fix unguarded del on forge update (critical #3)

**Files:**
- Modify: `tain_agent/tools/forge.py:363`

- [ ] **Step 1: Apply the fix**

In `_forge_register`, replace `del` with safe `pop`:

```python
# Old (line 363):
            del self._forged_tools[name]

# New:
            self._forged_tools.pop(name, None)
```

- [ ] **Step 2: Verify syntax**

Run: `python -c "from tain_agent.tools.forge import Forge; print('OK')"`
Expected: `OK`

- [ ] **Step 3: Run existing forge tests**

Run: `python -m pytest tests/test_forge_integration.py -v`
Expected: All tests pass

- [ ] **Step 4: Commit**

```bash
git add tain_agent/tools/forge.py
git commit -m "fix(forge): use safe pop instead of del to avoid KeyError on desync"
```

---

### Task 3: Fix H4 agent_name omission (high #8)

**Files:**
- Modify: `tain_agent/evolution/quality_gate.py:390`

- [ ] **Step 1: Apply the fix**

In `_h4_safety_boundary`, pass `agent_name` to `_workspace_dir`:

```python
# Old (line 390):
    ws = _workspace_dir()

# New:
    ws = _workspace_dir(agent_name)
```

- [ ] **Step 2: Verify syntax**

Run: `python -c "from tain_agent.evolution.quality_gate import _h4_safety_boundary; print('OK')"`
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add tain_agent/evolution/quality_gate.py
git commit -m "fix(quality-gate): pass agent_name to _workspace_dir in H4 for agent-scoped log lookup"
```

---

### Task 4: Fix H2 sys.modules pollution (critical #4)

**Files:**
- Modify: `tain_agent/evolution/quality_gate.py:291-298`

- [ ] **Step 1: Apply the fix**

In `_h2_tool_loadability`, add collision check and cleanup on failure:

```python
# Old (lines 291-298):
                    # Last resort: load from file path
                    spec = _util.spec_from_file_location(name, str(py_file))
                    if spec and spec.loader:
                        mod = _util.module_from_spec(spec)
                        sys.modules[name] = mod
                        spec.loader.exec_module(mod)
        except Exception as exc:
            failed.append(f"{name}: {exc}")

# New:
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
```

- [ ] **Step 2: Verify syntax**

Run: `python -c "from tain_agent.evolution.quality_gate import _h2_tool_loadability; print('OK')"`
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add tain_agent/evolution/quality_gate.py
git commit -m "fix(quality-gate): prevent sys.modules pollution in H2 fallback import path"
```

---

### Task 5: Fix S7 workspace fallback (high #5)

**Files:**
- Modify: `tain_agent/evolution/quality_gate.py:873-875`

- [ ] **Step 1: Apply the fix**

In `_s7_drive_integrity`, insert a global workspace fallback between the agent-specific path and the framework built-in path:

```python
# Old (lines 873-875):
    snapshots_dir = ws / "state" / "metrics_snapshots"
    if not snapshots_dir.exists():
        snapshots_dir = _project_root() / "tain_agent" / "state" / "metrics_snapshots"

# New:
    snapshots_dir = ws / "state" / "metrics_snapshots"
    if not snapshots_dir.exists():
        # Fallback 1: global agent_workspace
        global_ws = _workspace_dir()
        if global_ws:
            snapshots_dir = global_ws / "state" / "metrics_snapshots"
    if not snapshots_dir.exists():
        # Fallback 2: framework built-in
        snapshots_dir = _project_root() / "tain_agent" / "state" / "metrics_snapshots"
```

- [ ] **Step 2: Verify syntax**

Run: `python -c "from tain_agent.evolution.quality_gate import _s7_drive_integrity; print('OK')"`
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add tain_agent/evolution/quality_gate.py
git commit -m "fix(quality-gate): add global workspace fallback in S7 drive integrity path resolution"
```

---

### Task 6: Fix S9 dedup trend — structured snapshots + correct trend (critical #2 + high #6)

**Files:**
- Modify: `tain_agent/evolution/quality_gate.py:964-1039`

- [ ] **Step 1: Replace the S9 function body**

Replace the Markdown regex parsing logic with structured snapshot reading. The full replacement from line 986 to line 1039:

```python
    ws = _workspace_dir(agent_name)
    if ws is None:
        return ScoredResult("S9", "Code Dedup Trend", 0.50, 0.05,
                           "No workspace — cannot compare milestones",
                           {"current_count": current_count})

    # Use the same snapshots S7 reads (state/metrics_snapshots/metrics_*.json)
    snapshots_dir = ws / "state" / "metrics_snapshots"
    if not snapshots_dir.exists():
        global_ws = _workspace_dir()
        if global_ws:
            snapshots_dir = global_ws / "state" / "metrics_snapshots"
    if not snapshots_dir.exists():
        snapshots_dir = _project_root() / "tain_agent" / "state" / "metrics_snapshots"
    if not snapshots_dir.exists():
        return ScoredResult("S9", "Code Dedup Trend", 0.50, 0.05,
                           "No metrics snapshots found — need >= 2 evolution milestones",
                           {"current_count": current_count})

    snapshot_files = sorted(snapshots_dir.glob("metrics_*.json"))
    if len(snapshot_files) < 2:
        return ScoredResult("S9", "Code Dedup Trend", 0.50, 0.05,
                           "Need >= 2 metrics snapshots to establish trend",
                           {"current_count": current_count,
                            "snapshots_found": len(snapshot_files)})

    # Extract tool counts from the last 2 snapshots
    tool_counts = []
    for sf in snapshot_files[-2:]:
        try:
            data = json.loads(sf.read_text(encoding="utf-8"))
            te = data.get("tool_efficacy", {})
            count = te.get("total_tools", 0)
            tool_counts.append(count)
        except (json.JSONDecodeError, IOError, KeyError):
            continue

    if len(tool_counts) < 2:
        return ScoredResult("S9", "Code Dedup Trend", 0.50, 0.05,
                           "Could not extract tool counts from snapshots",
                           {"current_count": current_count})

    prev_count, latest_count = tool_counts
    trend_delta = latest_count - prev_count          # milestone trend
    current_delta = current_count - latest_count      # change since last snapshot

    # Score: reward dedup trend (negative trend_delta) with no rebound
    if trend_delta < 0:
        # Dedup trend active
        if current_delta <= 0:
            # Sustained or continued dedup — high score
            score = min(1.0, 0.85 + abs(trend_delta) * 0.1)
            detail = (f"Dedup trend active: {prev_count} -> {latest_count} "
                      f"({abs(trend_delta)} removed). Current: {current_count} — holding.")
        else:
            # Dedup trend but current rebound — moderate score
            score = max(0.45, 0.70 - current_delta * 0.15)
            detail = (f"Dedup reversed: {prev_count} -> {latest_count} "
                      f"(was trending down), now {current_count} (+{current_delta}).")
    elif trend_delta == 0:
        if current_delta == 0:
            score = 0.70
            detail = f"Tool count stable at {current_count} — no bloat detected"
        else:
            score = max(0.35, 0.60 - current_delta * 0.15)
            detail = f"Stable history broken: now {current_count} ({current_delta:+d})"
    else:
        # trend_delta > 0: bloat trend
        score = max(0.0, 0.45 - trend_delta * 0.15)
        detail = (f"Bloat trend: {prev_count} -> {latest_count} "
                  f"(+{trend_delta}). Current: {current_count}.")

    return ScoredResult(
        "S9", "Code Dedup Trend", round(score, 3), 0.05,
        detail,
        {"prev_count": prev_count, "latest_count": latest_count,
         "current_count": current_count,
         "trend_delta": trend_delta, "current_delta": current_delta},
    )
```

Also remove the now-unused reports_dir fallback block (lines 987-997 in the old code, which is the block between `ws = _workspace_dir(agent_name)` and the snapshot reading). The new code above starts from `ws = _workspace_dir(agent_name)` and goes directly into snapshot resolution.

- [ ] **Step 2: Verify syntax**

Run: `python -c "from tain_agent.evolution.quality_gate import _s9_dedup_trend; print('OK')"`
Expected: `OK`

- [ ] **Step 3: Run quality gate tests**

Run: `python -m pytest tests/test_quality_gate.py -v`
Expected: All tests pass

- [ ] **Step 4: Commit**

```bash
git add tain_agent/evolution/quality_gate.py
git commit -m "fix(quality-gate): replace S9 Markdown regex parsing with structured metrics snapshots"
```

---

### Task 7: Fix S2 cross-layer dependency with logging (high #7)

**Files:**
- Modify: `tain_agent/evolution/quality_gate.py:1-20` (imports), `tain_agent/evolution/quality_gate.py:660-667` (function body)

- [ ] **Step 1: Add logging import and top-level get_referenced_files import**

Add `import logging` after the existing `import os` (line 15):

```python
import logging
```

Add logger after `_now_iso()` (after line 23):

```python
logger = logging.getLogger(__name__)
```

Add the top-level import of `get_referenced_files` after the logger:

```python
try:
    from tain_agent.plugins.knowledge.lifecycle import get_referenced_files
except ImportError:
    get_referenced_files = None
    logger.warning(
        "Knowledge plugin unavailable — S2 knowledge coverage will not "
        "count cross-agent references."
    )
```

- [ ] **Step 2: Replace the in-function import**

In `_s2_knowledge_coverage`, replace the bare `try/except ImportError: pass` block (lines 660-667):

```python
# Old (lines 660-667):
    # v0.7.0: Count referenced knowledge files from other agents
    ref_count = 0
    try:
        from tain_agent.plugins.knowledge.lifecycle import get_referenced_files
        ref_files = get_referenced_files(agent_name) if agent_name else []
        ref_count = len(ref_files)
    except ImportError:
        pass

# New:
    # v0.7.0: Count referenced knowledge files from other agents
    ref_count = 0
    if get_referenced_files is not None and agent_name:
        try:
            ref_files = get_referenced_files(agent_name)
            ref_count = len(ref_files)
        except Exception:
            logger.warning(
                "Failed to count referenced knowledge files for agent '%s'",
                agent_name,
            )
```

- [ ] **Step 3: Verify syntax**

Run: `python -c "from tain_agent.evolution.quality_gate import _s2_knowledge_coverage; print('OK')"`
Expected: `OK`

- [ ] **Step 4: Run knowledge plugin tests**

Run: `python -m pytest tests/test_knowledge_plugin.py -v`
Expected: All tests pass

- [ ] **Step 5: Commit**

```bash
git add tain_agent/evolution/quality_gate.py
git commit -m "fix(quality-gate): move S2 get_referenced_files import to module level with logging"
```

---

### Task 8: Final verification

- [ ] **Step 1: Run all affected tests**

```bash
python -m pytest tests/test_quality_gate.py tests/test_forge_integration.py tests/test_knowledge_plugin.py -v
```

Expected: All tests pass

- [ ] **Step 2: Verify all modules import cleanly**

```bash
python -c "
from tain_agent.core.cognitive_loop import CognitiveLoop
from tain_agent.tools.forge import Forge
from tain_agent.evolution.quality_gate import (
    _h2_tool_loadability,
    _h4_safety_boundary,
    _s2_knowledge_coverage,
    _s7_drive_integrity,
    _s9_dedup_trend,
)
print('All imports OK')
"
```

Expected: `All imports OK`

- [ ] **Step 3: Final review of git log**

```bash
git log --oneline -7
```
