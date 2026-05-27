# P12 — Smart File Truncation

**Target:** v0.5.0
**Source:** [design doc supplement, section 3](../design/v0-4-2-design.md#智能截断)

## Current State

File reading tools return full content without truncation. Large log files or knowledge base entries can overflow context windows when read by the agent.

## Reference (Mini-Agent)

`truncate_text_by_tokens()` — head+tail preservation with middle truncation:
```
[前 50% content ...Content truncated: 120000 tokens → ~32000 tokens limit... 后 50% content]
```

## Implementation

### New file: `tain_agent/utils/token_utils.py`

```python
def estimate_tokens(text: str) -> int:
    """Fast estimate: len(text) / 2.5, or tiktoken if available."""
    try:
        import tiktoken
        enc = tiktoken.get_encoding("cl100k_base")
        return len(enc.encode(text))
    except ImportError:
        return int(len(text) / 2.5)

def truncate_text_by_tokens(text: str, max_tokens: int, head_ratio: float = 0.5) -> str:
    """Keep head_ratio of budget for start, rest for end, middle truncated."""
    if estimate_tokens(text) <= max_tokens:
        return text
    # Split, keep head and tail, insert truncation marker
    ...

def truncate_lines(text: str, max_lines: int) -> str:
    """Line-based truncation with head+tail preservation."""
    ...
```

### Modified files

- `tain_agent/tools/primal.py` — `read_file`, `read_logs`, `search_knowledge` apply truncation
- `webui/dialogue.py` — `_build_system_prompt()` truncates overly long tool descriptions
- `tain_agent/tools/templates.py` (from P7) — import and expose truncation utilities

### Config

```yaml
tools:
  max_output_tokens: 32000
  max_output_lines: 5000
```

## Verification

- Read a 100k-token file, confirm output is ~32k tokens with truncation marker
- Head and tail content both present
- Truncation marker shows original size and limit
- Small files (< limit) returned in full, no truncation applied
