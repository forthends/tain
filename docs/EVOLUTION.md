# What "Evolution" Means in Tain Agent Framework

## Honest Evolution

The Tain Agent Framework previously used an "LLM-judging-LLM" pattern for self-evaluation — the same LLM would answer benchmark questions and then score its own answers. This created a closed, self-referential loop with no external ground truth.

Starting from v0.10.0, "evolution" means **autonomous, framework-measured behavioral change over time**:

## What Is Measured

| Metric | Source | Description |
|--------|--------|-------------|
| Tool Success Rate | Cognitive loop telemetry | Ratio of successful tool calls to total calls |
| Action Diversity | Cognitive loop history | Number of distinct tools used vs. total actions |
| Drive Profile | DriveSystem | Four intrinsic drives (curiosity, mastery, creation, conservation) and their relative intensities |
| Code Health | AST analysis | Cyclomatic complexity, dead code detection |
| Knowledge Coverage | File system | Number of knowledge nodes and domains |
| Knowledge Freshness | File modification times | How recently knowledge was updated |
| Capability Coverage | CapabilityRegistry | Which desired capabilities have registered tools |

## What Is NOT Measured by LLM

- The agent's "intelligence" or "quality" of responses
- Subjective evaluation of creative output
- Whether the agent has "truly emerged" as conscious
- Self-reported personality traits without behavioral evidence

## Personality Evolution

Personality traits evolve through **behavioral observation**, not LLM introspection:

1. The framework tracks which tools the agent uses each cycle
2. Text outputs are scanned for communication patterns (direct expression, nuanced thinking)
3. Tool usage patterns trigger trait discovery or reinforcement in relevant categories

This replaces the old `_reinforce_personality` which artificially inflated confidence numbers by +0.05 per cycle regardless of actual behavior.

## Drive System

Four competing intrinsic drives create behavioral variation:

- **Curiosity (好奇)**: Satisfied by exploration tools (web_search, read_file, explore_directory)
- **Mastery (精进)**: Satisfied by improvement tools (regression_tester, assess_capabilities)
- **Creation (创造)**: Satisfied by generative tools (forge_tool, write_file, execute_code)
- **Conservation (守成)**: Satisfied by maintenance tools (evolve_report, complete_goal)

Drives are randomly initialized per agent instance, creating different behavioral tendencies. Drive weights are injected into the system prompt as soft guidance. When exploration pressure builds (from idle cycles), the framework injects exploration prompts.

## Quality Gate

The `ExportQualityGate` evaluates agent readiness for export using **only framework-measured criteria**:

- **Hard gates (H1-H7)**: File existence, import tests, AST analysis, safety boundary checks
- **Scoring gates (S1-S9)**: Tool success rate, knowledge coverage, tool chain coherence, action diversity, code health, knowledge freshness, drive integrity, external feedback, code dedup trend

No scoring gate uses LLM-as-judge. All scores come from file system, AST, registry, or telemetry data.

## Autonomous Evolution (v0.10.0)

The **AutonomousEvolutionLoop** closes the evolution loop — agents can now autonomously complete the full gap→deploy→verify cycle with zero human intervention:

1. **Gap Detection** — 8-dimension trigger assessment identifies improvement needs
2. **Code Generation** — LLM generates tool code with sandbox allowlist awareness
3. **Behavior Contract** — AST-verified import/side-effect boundary enforcement
4. **Sandbox Forging** — 7-stage safety pipeline (existing, unchanged)
5. **Online Verification** — Deployed tool tested with auto-generated inputs
6. **Quality Evaluation** — Pre/post quality delta comparison; automatic rollback on degradation

Three-layer safety: sandbox → behavior contract → automatic rollback. See [changelog/v0.10.0.md](changelog/v0.10.0.md) for details.

## What Evolution Is NOT

- The agent does not rewrite its own core code (self-modification is workspace-scoped)
- The agent does not "become smarter" through self-reflection — it accumulates behavioral data that the framework uses to describe it
- Confidence scores in personality traits represent consistency of observed behavior, not "correctness" of self-assessment
