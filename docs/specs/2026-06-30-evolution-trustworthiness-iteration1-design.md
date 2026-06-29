# Evolution Trustworthiness — Iteration 1 Design Spec

**Date**: 2026-06-30
**Base commit**: `a4d9d54` (third-party insight report) → `HEAD` (dev)
**Goal**: Make the autonomous evolution loop produce honest metrics, meaningful specs, and verifiable results — eliminating the "claimed ≠ delivered" gap identified by the insight report.

---

## Background

A third-party insight report (committed at `docs/report/tain-insight-reprot-20260629.md`) evaluated the framework at commit `a4d9d54`. It identified a core contradiction: the framework's flagship "autonomous evolution" feature was architecturally disconnected from the actual run path, and its metrics were self-deceptive. Six issues have been fixed since the report (evolution wired into PRALLoop, dead code removed, cross-platform sandbox env, agent state isolation, version unification, online verifier hardened). This spec covers the remaining gaps, organized as Iteration 1 of a two-iteration plan.

### Iteration 1 scope: "Make evolution trustworthy"

- Evolution metrics: eliminate circular-dependency stubs, connect to real signals
- Spec quality: inject task-specific context instead of template filler
- Engineering hygiene: sandbox bypass fix, broad-exception convergence on hot paths, runtime decoupling annotation fix
- Reproducibility: end-to-end demo script with mock LLM
- Honest labeling: experimental/stable mode distinction

### Out of scope (Iteration 2)

- Full codebase broad-exception cleanup beyond hot paths
- forge.py style unification
- Final documentation sweep beyond README
- Parameterized tool online verification with auto-generated arguments

---

## Section 1: Evolution Metrics Overhaul

### Problem

`AutonomousEvolutionLoop._assess_need()` evaluates 8 trigger dimensions. Five of them (`code_health`, `knowledge_fresh`, `tool_fitness`, `subgraph_balance`, `task_completion`) are either circular-dependency stubs (require pre-forged tools that don't exist on cold start → always return 0) or hardcoded to return 0.0. The remaining dimensions:

- `capability_gap`: scored purely on tool count (`(10 - count) / 10`) — encourages tool spam, not genuine capability growth
- `tool_dedup`: hash-based dedup check — valid but low weight (0.08)
- `goal_achievement`: from KnowledgePlugin.goals — the only real signal

Meanwhile, `PRALLoop._assess_evolution_need()` implements its own separate scoring (capability_gap 40% + goal_achievement 60%), creating two divergent metric paths.

### Design

**1. Delete circular-dependency dimensions**

Remove `_eval_code_health`, `_eval_knowledge_fresh`, `_eval_tool_fitness`, `_eval_subgraph_balance` from `_assess_need()`. These four dimensions depend on pre-forged tools (`code_entropy`, `knowledge_freshness`, `tool_fitness`, `knowledge_subgraph`) that never exist at cold start, so they can never produce non-zero signals. Their evaluator methods are removed alongside their `trigger_config` entries.

**2. Rewrite `_eval_capability_gap` to be goal-driven**

Instead of counting tools against an arbitrary threshold of 10, check `KnowledgePlugin.goals` for goals whose `required_capability` field lists capabilities not present in the current toolset:

```
For each uncompleted goal:
  If goal has required_capability not matching any existing tool:
    gap_count += 1
Score = gap_count / max(len(uncompleted_goals), 1)
```

If no goals exist or no goals declare `required_capability`, fall back to a milder version of tool-count scoring with a higher threshold (e.g., 3 tools instead of 10) and lower weight.

**3. Implement `_eval_task_completion`**

Query `KnowledgePlugin` for recent tool-call history (from `decision_log` or conversation records). Compute:

```
failures = count of tool calls with error/failure result
total = total recent tool calls
Score = failures / max(total, 1)
```

High failure rate → high evolution need. If no history available, return 0.0 (not 0.5 — don't invent a signal).

**4. Unified scoring**

PRALLoop's `_assess_evolution_need()` delegates to `AutonomousEvolutionLoop._assess_need()` or a shared function, removing the duplicate scoring path.

New dimension weighting:

| Dimension | Weight | Data source |
|---|---|---|
| capability_gap | 0.30 | goals.required_capability vs tools |
| tool_dedup | 0.10 | hash-based dedup |
| task_completion | 0.35 | tool call success rate |
| goal_achievement | 0.25 | goals completed / total |

### Files changed

- `tain_agent/evolution/autonomous_loop.py`: remove 4 stub evaluators; rewrite `_eval_capability_gap`; implement `_eval_task_completion`; update `trigger_config` and `_assess_need()` weights
- `tain_agent/runtime/pral.py`: `_assess_evolution_need()` delegates to shared function
- `tests/test_autonomous_evolution.py`: update dimension-related tests

---

## Section 2: Spec Generation Quality

### Problem

`_generate_spec()` produces descriptions from a hardcoded template (`"Fill capability gap"`, `"Improve code health"`, etc.) with no information about what the agent is actually trying to accomplish. The spec's `function_name` is auto-incremented (`auto_capability_gap`, `auto_capability_gap_2`, ...) and its `reasoning` is a mechanical score dump. LLM receives a generic prompt and generates generic code — the report correctly calls this "meaningless filler."

### Design

**1. Inject goal context into spec**

Before building the spec, query `KnowledgePlugin.goals` for uncompleted goals. If an uncompleted goal has a `description` and optional `required_capability`, use them as the semantic anchor:

```python
# Before: "Fill capability gap"
# After:  "Add tool for CSV data analysis: supports goal 'analyze sales data'"
```

The `function_name` derives from the goal's `required_capability` (if present) rather than `auto_<dim>`:

```python
# Before: "auto_capability_gap"
# After:  "csv_analyzer" (from goal.required_capability)
```

**2. Inject failure feedback into reasoning**

When `task_completion` dimension triggered the cycle, query `decision_log` for recently failed tool calls. Include the failure signatures in `reasoning`:

```python
reasoning = (
    "Triggered by task_completion: recent tool 'data_parser' failed 3/5 calls "
    "with TypeError on CSV input. Need replacement or supplemental tool. "
    f"Scores: {scores_summary}"
)
```

**3. Enrich `_build_generation_prompt`**

Pass the full goal description, required capability, and failure examples into the LLM prompt so the generated code targets a concrete task rather than a generic description.

### Files changed

- `tain_agent/evolution/autonomous_loop.py`: `_generate_spec()` data collection; `_build_generation_prompt()` enrichment
- `tests/test_autonomous_evolution.py`: verify goal/failure context in generated specs

---

## Section 3: Engineering Hygiene

### 3a. Sandbox whitelist bypass (P2-8)

**Problem**: `_build_sandbox_test_script()` (`autonomous_loop.py:1279-1289`) skips whitelist/blacklist checks when the import name contains a dot — `import os.path` or `import urllib.request` passes through unchecked.

**Fix**: Extract the top-level package name (`alias.name.split('.')[0]`) and apply the same allowlist/blocklist check. Applies to both `ast.Import` and `ast.ImportFrom` branches.

### 3b. Broad-exception convergence on hot paths (P2-9)

**Problem**: 181 instances of `except Exception` across the codebase. The PRAL loop alone has 12, masking failures in `_perceive()`, `_learn()`, `_notify_plugins()`, etc.

**Fix (Iteration 1 scope — hot paths only)**:

- `pral.py:_perceive()`: plugin query failures → `except (AttributeError, RuntimeError)` with logger.debug
- `pral.py:_notify_plugins()`: callback failures → same pattern
- `pral.py:_save_memory_state()`: IO failures → `except (OSError, ValueError)`
- `autonomous_loop.py`: dimension evaluator try/except removed alongside stub deletion in Section 1; remaining evaluators narrowed to specific exceptions

**Principle**: `except Exception: pass` → `except (SpecificTypes) as e: logger.debug("context: %s", e)`

### 3c. Runtime decoupling annotation (P2-10)

**Problem**: `runtime/__init__.py:9` declares "no import tain_agent" but lines 16-20 import `tain_agent.kernel.*` and `tain_agent.package.*`.

**Fix**: Replace the inaccurate constraint with an honest one:

```
Design constraint: runtime/ depends only on tain_agent.kernel.* (protocol
layer) and tain_agent.package.* (packaging layer). No dependency on plugins,
evolution, core, or any I/O-heavy subsystem.
```

No code changes needed — the actual imports are appropriate.

### Files changed

- `tain_agent/evolution/autonomous_loop.py`: sandbox bypass fix
- `tain_agent/runtime/pral.py`: exception narrowing on hot paths
- `tain_agent/runtime/__init__.py`: docstring only

---

## Section 4: Reproducible End-to-End Experiment

### Problem

The report's most damaging criticism: "no reproducible experiment proves evolution produces real value." Without one, all claims about autonomous improvement remain unsubstantiated.

### Design

New file: `scripts/demo_evolution.py`.

```
Given: a minimal Agent (2 tools, 1 uncompleted goal)
  → gap_detector identifies capability gap (goal requires a tool not present)
  → mutation_generator produces targeted tool code (via mock LLM returning preset code)
  → contract_checker validates the code
  → online_verifier sandbox-tests it
  → tool registered successfully AND/OR
  → bad code path: generated code calls blocked function → contract intercept → rollback

Output: PASS/FAIL with structured result (JSON to stdout)
Exit code: 0 = evolution succeeded; 1 = expected failure not reproduced; 2 = unexpected error
```

Constraints:
- Uses mock LLM backend (returns preset valid/invalid code) — no API key, no network
- Runs in CI: `python scripts/demo_evolution.py` deterministically
- Two paths: (a) valid tool → forge succeeds → tool count increases; (b) blocked import → contract check fails → no tool added
- The demo script is self-contained — imports from the framework but injects mocks at defined interfaces

### Files changed

- `scripts/demo_evolution.py` (new)
- CI configuration: add demo script to test suite (optional, can be manual for now)

---

## Section 5: Honest Labeling

### Problem

README promises "zero human intervention" autonomous evolution. The report notes this is marketing-speak that doesn't match reality. For a framework that builds its philosophy on "honest evolution," the labeling itself is dishonest.

### Design

**1. `evolution.mode` config field**

```yaml
evolution:
  enabled: true
  mode: "experimental"  # experimental | stable
  min_interval_seconds: 300
  max_improvements_per_session: 3
  min_trigger_score: 0.3
```

Default: `"experimental"`.

**2. Runtime notification**

When `mode == "experimental"`, `PRALLoop._trigger_evolution()` injects a system advisory into the conversation on first evolution trigger:

```
Autonomous evolution is enabled in EXPERIMENTAL mode. Generated tools may
be low-quality or non-functional. All generated tools are sandbox-tested
and automatically rolled back on failure. Evolution metrics and quality
gates are under active development.
```

**3. README alignment**

Replace "zero human intervention" narrative with honest capability descriptions:

| Capability | Status | Notes |
|---|---|---|
| Autonomous tool generation | Experimental | Gated, rate-limited, auto-rollback on failure |
| Behavior contract enforcement | Stable | AST-level import/call validation |
| Multi-provider LLM (Anthropic/OpenAI) | Stable | Via respective SDKs |
| WebUI (SSE streaming) | Stable | FastAPI + SSE |
| MCP/ACP server | Beta | Protocol support, limited tool coverage |

### Files changed

- `tain_agent/runtime/pral.py`: `_get_evolution_config()` reads `mode`; `_trigger_evolution()` adds experimental advisory
- `README.md`: capability status table, honest language

---

## Summary

| Change area | Core changes | Files affected |
|---|---|---|
| Evolution metrics | Delete 4 stub evaluators; rewrite `_eval_capability_gap` and `_eval_task_completion`; unify PRALLoop metric path | 2-3 |
| Spec quality | `_generate_spec()` queries goals/failures; `_build_generation_prompt()` enriched | 1-2 |
| Engineering hygiene | Sandbox bypass fix; exception narrowing on hot paths; runtime docstring | 3-4 |
| Reproducible experiment | New `scripts/demo_evolution.py` with mock LLM, two-path demo | 1 |
| Honest labeling | `evolution.mode` config; experimental advisory; README update | 2-3 |
| Tests | Updated dimension tests; demo script assertions | 2-3 |

**Total files**: 12-14. **Test baseline**: 829 passing (must not regress).

### Risks

- **Goal schema dependency**: Section 1 and 2 assume `KnowledgePlugin.goals` entries have `required_capability` and `description` fields. If goals are unstructured, fallback to existing behavior with lower weight.
- **Mock LLM fidelity**: The demo script's mock must produce output that passes through `_parse_generated_response()` — need to match the expected format exactly.

### Success criteria

1. All existing 829 tests continue to pass
2. `demo_evolution.py` exits 0 and demonstrates both success and rollback paths
3. `_assess_need()` no longer references `code_entropy`, `knowledge_freshness`, `tool_fitness`, or `knowledge_subgraph`
4. `_eval_task_completion()` returns a value derived from actual tool-call history, not a hardcoded constant
5. Sandbox AST validation catches `import os.path` as a blocked import
6. README contains no unqualified "zero human intervention" claims about unproven features
