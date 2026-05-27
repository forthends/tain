# P11 — Multi-Level Config Search

**Target:** v0.5.0
**Source:** [design doc supplement, section 1](../design/v0-4-2-design.md#借鉴意义)

## Current State

Single `config.yaml` in project root. No support for per-environment, per-user, or per-agent configuration overrides.

## Reference (Mini-Agent)

Multi-level config search with precedence: workspace > user > package defaults.

## Implementation

### New file: `tain_agent/core/config.py` (or extend existing config loading)

```python
# Search order (first found wins):
# 1. --config CLI flag (explicit path)
# 2. ./config.yaml (project root / workspace)
# 3. ~/.tain/config.yaml (user-level)
# 4. package defaults (built-in)

def load_config(explicit_path=None) -> dict:
    paths = [
        explicit_path,
        Path.cwd() / "config.yaml",
        Path.home() / ".tain" / "config.yaml",
    ]
    config = DEFAULT_CONFIG.copy()
    for path in paths:
        if path and Path(path).exists():
            deep_merge(config, yaml.safe_load(path.read_text()))
    return config
```

### Per-agent overrides

`agent_workspace/<name>/agent.yaml` — agent-specific config merged on top:
```yaml
llm:
  model: "MiniMax-M2.7"
personality:
  traits: ["analytical", "curious"]
```

## Verification

- User-level `~/.tain/config.yaml` with `retry.max_retries: 5` overrides default
- Agent-level `agent.yaml` overrides user-level for that agent only
- CLI `--config /path/to/config.yaml` takes highest precedence
- Missing optional levels don't error
