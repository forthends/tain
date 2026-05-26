# P4 — Agent Memory Tools

**Target:** v0.4.5
**Source:** [design doc, gap #4](../design/v0-4-2-design.md#4-agent-主动记忆工具--tain-部分缺失)

## Current State

`SessionMemory` records per-session summaries, but agent cannot **actively** call a tool to save discoveries during evolution. `Memory.remember()` exists but is not exposed as a callable tool.

## Reference (Mini-Agent)

- `SessionNoteTool` (`record_note`) — agent writes `{timestamp, category, content}` to `.agent_memory.json`
- `RecallNoteTool` (`recall_notes`) — retrieves notes, optionally filtered by category
- Lazy initialization: file created on first write
- Pure JSON file, no external database

## Implementation

### New primal tools

Register in `tain_agent/tools/primal.py`:

**`remember_note`**
```
Parameters:
  - category: string (e.g., "discovery", "user_preference", "pattern")
  - content: string (the note body)
→ appends {"timestamp": ..., "category": ..., "content": ...} to memory file
→ stored at agent_workspace/<name>/memory/notes.jsonl
```

**`recall_notes`**
```
Parameters:
  - category: string (optional filter)
  - limit: int (default 20)
→ returns matching notes sorted by recency
```

### Integration

- Agent evolution loop: after each `evolve` phase, prompt agent to save key findings via `remember_note`
- `_build_system_prompt()` in `webui/dialogue.py`: include recent notes in prompt context
- Memory system's existing `remember()` / `recall()` methods reused as backend

## Verification

- Agent in evolution loop discovers a pattern and calls `remember_note`
- Notes persist across restarts
- `recall_notes` with category filter returns correct subset
- Web UI "Knowledge" tab shows memory notes alongside knowledge files
