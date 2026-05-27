# P7 — Forge Tool Templates

**Target:** v0.4.5
**Source:** [design doc supplement, section 3](../design/v0-4-2-design.md#智能截断)

## Current State

`ToolForge` generates tools from scratch each time with no standard patterns. Common concerns — workspace isolation, output truncation, error handling — are handled inconsistently across forged tools.

## Reference (Mini-Agent)

- `ReadTool/WriteTool/EditTool` — workspace-relative path resolution
- `truncate_text_by_tokens()` — head+tail preservation with middle truncation
- `BashTool` — async process with timeout and output capture
- Each tool holds its own `workspace_dir` reference

## Implementation

### New file: `tain_agent/tools/templates.py`

Provide template functions that forged tools can compose:

- `resolve_path(workspace_dir, path)` — resolve relative paths safely within workspace
- `truncate_output(text, max_tokens)` — head+tail truncation with middle indicator
- `run_shell(command, timeout, workspace_dir)` — async subprocess with timeout
- `format_error(message, exception)` — consistent error formatting

### Modified: `tain_agent/tools/forge.py`

- Forge prompt includes template functions as "available utilities"
- Generated code imports from `tain_agent.tools.templates`
- Reduces boilerplate in forged tool code

## Verification

- Forged tool using `resolve_path` cannot escape workspace
- Forged tool using `truncate_output` doesn't exceed context
- Forged tool using `run_shell` properly handles timeout
- Templates are importable and usable independently of forge
