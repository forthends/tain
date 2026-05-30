# Safety & Security Model

## Tool Execution

### Sandbox (forged tools)

Tools created via the ToolForge pass through a multi-stage safety pipeline:

1. **AST-based import whitelist** — only safe standard library modules allowed (`json`, `datetime`, `pathlib`, `re`, `math`, `collections`, `itertools`, `functools`, `hashlib`, `textwrap`, `string`, `dataclasses`, `enum`, `uuid`, `statistics`, `csv`, `copy`, `random`, `html`, `xml`, `argparse`, `logging`)

2. **AST-based call blacklist** — resolved through import alias map to catch indirect calls like `from os import system; system(...)`. Blocks: `os.*`, `sys.*`, `subprocess.*`, `shutil.*`, `socket.*`, `ctypes.*`, `multiprocessing.*`, `signal.*`, `builtins.eval/exec/__import__/compile`

3. **Subprocess isolation** — smoke test execution runs in a separate process with `subprocess.run(timeout=10)`, restricted `PYTHONPATH` and `PATH`

4. **Path escape detection** — AST scan for absolute paths and parent-directory traversals

5. **No sandbox = no forge** — if the sandbox module fails to load, tool forging is disabled entirely (returns `passed: False`)

### Primal tools

Built-in tools execute with thread-pool timeout protection (60s default, 120s for network tools). They do not pass through the forge sandbox.

## Workspace Isolation

- Each agent operates in `agent_workspace/<name>/`
- Path resolution validates that all file operations stay within the workspace
- Symlinks are rejected — `resolve_content_path` detects and blocks symlink traversal
- Parent-directory traversal (`../`) is rejected
- Absolute filesystem paths are rejected

## MCP Integration

External MCP servers are subject to security constraints:

- **Command whitelist**: only `npx`, `node`, `python`, `python3`, `uvx` (extendable via `TAIN_MCP_COMMAND_WHITELIST` env var)
- **Shell injection detection**: args containing `;`, `|`, `&&`, `||`, `$`, backtick are rejected
- **Env var safelist**: dangerous vars (`LD_PRELOAD`, `PYTHONSTARTUP`, `NODE_OPTIONS`, etc.) are stripped
- **Startup timeout**: 30s timeout prevents hung servers

## ACP Protocol

The ACP server validates that workspace paths are within `agent_workspace/`. Paths outside are rejected with error code `-32001`.

## What Is NOT Protected

- **Network egress**: forged tools can make network requests (whitelisted `urllib` not enabled, but the sandbox doesn't intercept socket-level access at the OS level)
- **Resource exhaustion**: no CPU/memory limits in the subprocess sandbox beyond the 10s timeout
- **Side-channel attacks**: no protection against timing or filesystem metadata attacks
- **LLM prompt injection**: the LLM itself may be manipulated through crafted inputs

## Reporting Security Issues

Please report security vulnerabilities privately. Do not file public issues.
