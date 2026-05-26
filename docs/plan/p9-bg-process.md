# P9 — Background Process Management

**Target:** v0.5.0
**Source:** [design doc supplement, section 3](../design/v0-4-2-design.md#后台进程管理)

## Current State

No mechanism for agent to run long-lived commands. Agent evolution sometimes needs to start servers, run test suites, or execute batch operations — all of which exceed typical tool execution timeouts.

## Reference (Mini-Agent)

- `BashTool` + `BackgroundShellManager`
- Start long-running commands asynchronously
- Monitor output incrementally
- Kill by process ID
- `BashOutputTool` reads new output since last check

## Implementation

### New file: `tain_agent/tools/background_manager.py`

```python
class BackgroundProcess:
    id: str
    command: str
    process: asyncio.subprocess.Process
    started_at: str
    output_buffer: list[str]

class BackgroundShellManager:
    processes: dict[str, BackgroundProcess]

    async def start(self, command, workspace_dir) -> str  # returns process_id
    async def get_output(self, process_id, tail_lines) -> str
    async def kill(self, process_id) -> bool
    async def list_processes(self) -> list[dict]
    async def wait(self, process_id, timeout) -> dict  # {exit_code, output}
```

### New primal tools

- `bg_start` — `BackgroundShellManager.start()`
- `bg_output` — `BackgroundShellManager.get_output()`
- `bg_kill` — `BackgroundShellManager.kill()`
- `bg_list` — `BackgroundShellManager.list_processes()`
- `bg_wait` — `BackgroundShellManager.wait()`

### Safety constraints

- Commands run in agent's workspace directory
- Shell metacharacters sanitized or commands run via subprocess (no shell)
- Process limit per agent (configurable, default 5)
- Auto-kill all processes on agent stop/restart

## Verification

- Start `python -m http.server 0` in background, confirm process listed
- Read output, confirm HTTP server logs
- Kill process, confirm port released
- Agent stop → all background processes terminated
