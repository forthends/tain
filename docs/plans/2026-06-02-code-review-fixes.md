# 代码审查修复实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修复 `dev` vs `main` 代码审查报告中确认的 10 个缺陷，当前 `dev` 分支上逐一修复，每个修复独立提交。

**Architecture:** 10 个修复分为 5 组（Kernel 崩溃、WebUI 安全、Kernel 健壮性、MCP 协议、功能+效率+UX），各组之间完全独立。每个修复改动局限在 1-2 个文件，改动量小（1-40 行），风险可控。

**Tech Stack:** Python 3.12+, pytest, bash

---

### Task 1: 修复 PRAL `_perceive()` 调用签名

**Files:**
- Modify: `tain_agent/kernel/pral.py:66,69`

- [ ] **Step 1: 确认当前文件内容**

```bash
sed -n '62,76p' tain_agent/kernel/pral.py
```

Expected: 显示 `_perceive()` 方法，第 66 行为 `ctx["memories"] = mem.recall("recent context", k=5)`，第 69 行为 `ctx["knowledge"] = kw.query("recent topic")`。

- [ ] **Step 2: 修复调用签名**

编辑 `tain_agent/kernel/pral.py`，将第 66 行：
```python
            ctx["memories"] = mem.recall("recent context", k=5)
```
改为：
```python
            ctx["memories"] = mem.recall(limit=5)
```

将第 69 行：
```python
            ctx["knowledge"] = kw.query("recent topic")
```
改为：
```python
            ctx["knowledge"] = kw.query(limit=5)
```

- [ ] **Step 3: 运行 kernel 测试确认无回归**

```bash
python -m pytest tests/test_kernel.py -v --tb=short
```

Expected: 所有测试 PASS。

- [ ] **Step 4: 提交**

```bash
git add tain_agent/kernel/pral.py
git commit -m "$(cat <<'EOF'
fix(kernel): correct recall/query argument signatures in _perceive()

mem.recall("recent context", k=5) → mem.recall(limit=5) aligned with
MemoryPlugin.recall(limit: int, min_strength: float). Also fix
kw.query("recent topic") → kw.query(limit=5) to match KnowledgePlugin.
EOF
)"
```

---

### Task 2: 补齐 TaoAgentCompat 缺失属性

**Files:**
- Modify: `tain_agent/compat.py`

- [ ] **Step 1: 确认 main.py 中对 agent 的调用**

```bash
grep -n "agent\.print_state\|agent\.decision_log\|agent\.backend\|agent\.conversation\|agent\.tools\|agent\.memory\|agent\.goals\|agent\.forge\|agent\.config" main.py
```

Expected: 显示多处引用。

- [ ] **Step 2: 为 TaoAgentCompat 添加缺失属性和方法**

编辑 `tain_agent/compat.py`，在 `__init__` 方法末尾（`logger.info(...)` 行之后）添加：

```python
        # Legacy attribute proxies for main.py compatibility
        self._backend = None
        self._conversation = None
        self._drives = None
        self._config = config
        self._decision_log_entries: list[dict] = []

在 `run()` 方法的 `LLMBackend(backend_config)` 之后，将实例挂到 self 上：

```python
        backend = LLMBackend(backend_config)
        self._backend = backend
```

在 `ConversationManager(...)` 之后：

```python
        conversation = ConversationManager(
            workspace=str(self.kernel.ctx.workspace_path),
            agent_name=self.kernel.ctx.agent_name,
        )
        self._conversation = conversation
```

在 `DriveSystem()` 之后：

```python
        drives = DriveSystem()
        self._drives = drives
```

在 `stop()` 方法之后、`health_check()` 方法之前添加代理属性和方法：

```python
    # ── Legacy attribute proxies for main.py / DialogueBridge ──────

    @property
    def backend(self):
        return self._backend

    @property
    def config(self):
        return self._config

    @property
    def conversation(self):
        return self._conversation

    @property
    def tools(self):
        return None  # new kernel uses plugin dispatch, no direct tools ref

    @property
    def memory(self):
        return None  # new kernel uses MemoryPlugin, no direct memory ref

    @property
    def forge(self):
        return None  # tool forge not ported to new kernel yet

    @property
    def goals(self):
        return None  # goal system not ported to new kernel yet

    @property
    def decision_log(self):
        return _DecisionLogShim(self._decision_log_entries)

    def print_state(self) -> None:
        """Print agent state in a format compatible with old TaoAgent."""
        print(f"\n  Agent: {self.agent_name}")
        print(f"  Version: {self.framework_version}")
        print(f"  Phase: {self.phase}")
        print(f"  Cycle: {self.cycle_count}")
        print()
        for name, health in self.kernel.lifecycle.all_health_checks().items():
            status = getattr(health, 'status', str(health))
            print(f"  [{name}] {status}")
        print()
```

在文件顶部导入区域之后、`_FACTORIES` 之前添加 shim 类：

```python
class _DecisionLogShim:
    """Minimal shim so agent.decision_log.read_all() doesn't crash."""
    def __init__(self, entries: list[dict]):
        self._entries = entries

    def read_all(self) -> list[dict]:
        return list(self._entries)

    def filter_by_phase(self, phase: str) -> list[dict]:
        return [e for e in self._entries if e.get("phase") == phase]
```

- [ ] **Step 3: 验证语法正确**

```bash
python -m py_compile tain_agent/compat.py && echo "OK"
```

Expected: `OK`

- [ ] **Step 4: 运行兼容性测试**

```bash
python -m pytest tests/test_agent_bundle.py tests/test_ide_kernel.py -v --tb=short
```

Expected: 所有测试 PASS。

- [ ] **Step 5: 提交**

```bash
git add tain_agent/compat.py
git commit -m "$(cat <<'EOF'
fix(compat): add missing TaoAgentCompat attributes and shims

Add print_state(), decision_log, backend, conversation, config,
tools, memory, forge, goals property proxies so --new-kernel works
with --state, --log, --dialogue, and Ctrl+C handler.
EOF
)"
```

---

### Task 3: 修复 Markdown 渲染器 XSS 漏洞

**Files:**
- Modify: `webui/render.py:87-89`

- [ ] **Step 1: 确认当前代码**

```bash
sed -n '83,100p' webui/render.py
```

- [ ] **Step 2: 添加 URL scheme 白名单校验**

编辑 `webui/render.py`，在 `_inline_render` 函数中的 `t = escape(text)` 之后、正则替换之前，添加安全 URL 校验函数。在 `_inline_render` 函数定义之前（`def flush_blockquote` 之后）添加：

```python
    _SAFE_SCHEMES = ("http:", "https:", "mailto:", "#")

    def _safe_url(url: str) -> str:
        """Return url if safe, '#blocked' otherwise."""
        stripped = url.strip().lower()
        if any(stripped.startswith(s) for s in _SAFE_SCHEMES):
            return url
        return "#blocked"
```

然后修改第 87、89 行的正则替换，将 `\2` 包装为 `_safe_url` 调用。但这里 `_safe_url` 是内部函数，不能直接在正则替换字符串中调用。改为使用 `re.sub` 的回调函数形式。

将第 87 行：
```python
        t = re.sub(r"!\[([^\]]*)\]\(([^)]+)\)", r'<img src="\2" alt="\1">', t)
```
改为：
```python
        t = re.sub(r"!\[([^\]]*)\]\(([^)]+)\)",
                   lambda m: f'<img src="{_safe_url(m.group(2))}" alt="{m.group(1)}">', t)
```

将第 89 行：
```python
        t = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r'<a href="\2" class="text-blue-500 hover:underline">\1</a>', t)
```
改为：
```python
        t = re.sub(r"\[([^\]]+)\]\(([^)]+)\)",
                   lambda m: f'<a href="{_safe_url(m.group(2))}" class="text-blue-500 hover:underline">{m.group(1)}</a>', t)
```

- [ ] **Step 3: 运行渲染测试**

```bash
python -m pytest tests/ -k "render" -v --tb=short 2>&1 | tail -20
```

- [ ] **Step 4: 手动验证 XSS 防护**

```bash
python3 -c "
from webui.render import render_markdown
html = render_markdown('[click](javascript:alert(1))')
assert 'javascript:' not in html, f'XSS not blocked: {html}'
assert '#blocked' in html, f'Expected #blocked: {html}'
print('OK: javascript: blocked')

html2 = render_markdown('[safe](https://example.com)')
assert 'https://example.com' in html2
print('OK: https: allowed')
"
```

Expected: `OK: javascript: blocked` 和 `OK: https: allowed`

- [ ] **Step 5: 提交**

```bash
git add webui/render.py
git commit -m "$(cat <<'EOF'
fix(webui): block dangerous URL schemes in markdown link rendering

Add URL scheme whitelist (http, https, mailto, #) to _inline_render(),
blocking javascript:, data:, vbscript: and other dangerous schemes
in both image src and link href attributes.
EOF
)"
```

---

### Task 4: 修复 Dispatch.call() 异常吞噬

**Files:**
- Modify: `tain_agent/kernel/dispatch.py:28-30`

- [ ] **Step 1: 确认当前代码**

```bash
cat tain_agent/kernel/dispatch.py
```

- [ ] **Step 2: 修改异常处理逻辑**

编辑 `tain_agent/kernel/dispatch.py`，将 `call` 方法中的 `except Exception` 块从返回 `None` 改为返回错误描述字符串：

将第 28-30 行：
```python
        except Exception:
            logger.exception("Dispatch %r failed", event)
            return None
```
改为：
```python
        except Exception as exc:
            logger.exception("Dispatch %r failed", event)
            return f"[Dispatch Error] {event}: {exc}"
```

- [ ] **Step 3: 运行测试确认无回归**

```bash
python -m pytest tests/test_kernel.py tests/test_plugin_protocol.py -v --tb=short
```

Expected: 所有测试 PASS。

- [ ] **Step 4: 提交**

```bash
git add tain_agent/kernel/dispatch.py
git commit -m "$(cat <<'EOF'
fix(kernel): surface dispatch handler errors instead of swallowing them

Return error string from Dispatch.call() on handler failure instead
of None, so PRAL._act() injects real error info into tool_result
rather than a generic placeholder.
EOF
)"
```

---

### Task 5: 修复 MCP JSON-RPC 批量请求崩溃

**Files:**
- Modify: `tain_agent/mcp/server.py:41-48`

- [ ] **Step 1: 确认当前代码**

```bash
sed -n '37,48p' tain_agent/mcp/server.py
```

- [ ] **Step 2: 添加批量请求处理**

编辑 `tain_agent/mcp/server.py`，将 `_serve_stdio` 方法中的第 41-48 行：

```python
            try:
                req = json.loads(line)
                resp = self._handle_request(req)
                sys.stdout.write(json.dumps(resp, ensure_ascii=False) + "\n")
                sys.stdout.flush()
            except json.JSONDecodeError:
                sys.stdout.write(json.dumps({"jsonrpc":"2.0","error":{"code":-32700,"message":"Parse error"},"id":None}) + "\n")
                sys.stdout.flush()
```

改为：

```python
            try:
                req = json.loads(line)
                if isinstance(req, list):
                    responses = [self._handle_request(r) for r in req]
                    responses = [r for r in responses if r is not None]
                    if responses:
                        sys.stdout.write(json.dumps(responses, ensure_ascii=False) + "\n")
                        sys.stdout.flush()
                else:
                    resp = self._handle_request(req)
                    sys.stdout.write(json.dumps(resp, ensure_ascii=False) + "\n")
                    sys.stdout.flush()
            except json.JSONDecodeError:
                sys.stdout.write(json.dumps({"jsonrpc":"2.0","error":{"code":-32700,"message":"Parse error"},"id":None}) + "\n")
                sys.stdout.flush()
```

- [ ] **Step 3: 运行 MCP 测试**

```bash
python -m pytest tests/test_mcp_server.py -v --tb=short
```

Expected: 所有测试 PASS。

- [ ] **Step 4: 提交**

```bash
git add tain_agent/mcp/server.py
git commit -m "$(cat <<'EOF'
fix(mcp): handle JSON-RPC batch requests in stdio server

Detect list-type requests from json.loads and dispatch each element
individually, collecting non-null responses into a result array.
Prevents AttributeError crash when MCP clients send batch requests.
EOF
)"
```

---

### Task 6: 修复 MCP JSON-RPC 位置参数处理

**Files:**
- Modify: `tain_agent/mcp/server.py:60`

- [ ] **Step 1: 确认当前代码**

```bash
sed -n '58,61p' tain_agent/mcp/server.py
```

Expected: `result = handler(**params) if isinstance(params, dict) else handler()`

- [ ] **Step 2: 修复参数分发**

编辑 `tain_agent/mcp/server.py`，将第 60 行：
```python
            result = handler(**params) if isinstance(params, dict) else handler()
```
改为：
```python
            result = handler(*params) if isinstance(params, list) else handler(**params)
```

- [ ] **Step 3: 运行 MCP 测试**

```bash
python -m pytest tests/test_mcp_server.py -v --tb=short
```

Expected: 所有测试 PASS。

- [ ] **Step 4: 提交**

```bash
git add tain_agent/mcp/server.py
git commit -m "$(cat <<'EOF'
fix(mcp): support positional (array) params in JSON-RPC dispatch

handler(**params) only handled dict params; list params (valid per
JSON-RPC 2.0 spec) were dispatched as zero-argument calls, silently
dropping all parameters. Fix: handler(*params) for list, **params for dict.
EOF
)"
```

---

### Task 7: 修复评估插件死代码

**Files:**
- Modify: `tain_agent/plugins/evaluation/__init__.py:108-109,153-154`

- [ ] **Step 1: 确认当前代码**

```bash
sed -n '101,131p' tain_agent/plugins/evaluation/__init__.py
```

- [ ] **Step 2: 移除死代码守卫并标记 TODO**

编辑 `tain_agent/plugins/evaluation/__init__.py`，将第 108-109 行：
```python
        if not plugin_metrics:
            return None
```
改为：
```python
        # Allow empty metrics to produce a baseline snapshot
```

将第 153-154 行：
```python
    def _collect_metrics(self) -> dict[str, dict]:
        return {}
```
改为：
```python
    def _collect_metrics(self) -> dict[str, dict]:
        # TODO: wire real plugin metric sources (memory, tool, workflow stats)
        return {}
```

- [ ] **Step 3: 运行评估测试**

```bash
python -m pytest tests/test_evaluation_plugin.py -v --tb=short
```

Expected: 所有测试 PASS（注意快照生成行为可能有变化，观察测试输出）。

- [ ] **Step 4: 提交**

```bash
git add tain_agent/plugins/evaluation/__init__.py
git commit -m "$(cat <<'EOF'
fix(evaluation): remove dead early-return guard, allow baseline snapshots

Remove `not plugin_metrics: return None` guard so the evaluation
engine can produce baseline snapshots even with empty metric sets.
Add TODO for wiring real metric sources to _collect_metrics().
EOF
)"
```

---

### Task 8: 修复 drive_system 在新内核中被忽略

**Files:**
- Modify: `tain_agent/kernel/pral.py:20-21,78-98`

- [ ] **Step 1: 确认 pral.py run() 和 _build_prompt() 方法**

```bash
sed -n '20,98p' tain_agent/kernel/pral.py
```

- [ ] **Step 2: 存储 drive_system 引用并在 _build_prompt 中使用**

编辑 `tain_agent/kernel/pral.py`。首先在 `__init__` 中添加 drive_system 存储：

```python
    def __init__(self, lifecycle: LifecycleManager, dispatch: Dispatch):
        self._lm = lifecycle
        self._dispatch = dispatch
        self._running = False
        self.cycle_count = 0
        self._drive_system = None
```

然后在 `run()` 方法开头存储引用。在第 23 行 `self._running = True` 之前添加：

```python
    def run(self, llm_backend, conversation, drive_system, system_prompt_template: str,
            max_cycles: int | float = float("inf"), stop_signal: callable = None) -> int:
        """Execute PRAL cycles until stop."""
        self._drive_system = drive_system
        self._running = True
```

最后在 `_build_prompt()` 方法末尾（第 97 行 `# Drive system enriches the prompt too (not a plugin)` 注释之后）实现实际的驱动权重注入。将第 97-98 行：

```python
        # Drive system enriches the prompt too (not a plugin)
        return prompt
```

改为：

```python
        # Drive system enriches the prompt too (not a plugin)
        if self._drive_system is not None:
            try:
                weights = self._drive_system.get_weights()
                drive_lines = [f"observation: {weights.get('observation', 0):.2f}",
                               f"optimization: {weights.get('optimization', 0):.2f}",
                               f"creation: {weights.get('creation', 0):.2f}",
                               f"maintenance: {weights.get('maintenance', 0):.2f}"]
                prompt = prompt + "\n\n[Drive Weights]\n" + " | ".join(drive_lines)
            except Exception:
                logger.debug("Failed to read drive weights for prompt enrichment")
        return prompt
```

- [ ] **Step 3: 验证语法正确**

```bash
python -m py_compile tain_agent/kernel/pral.py && echo "OK"
```

Expected: `OK`

- [ ] **Step 4: 运行测试**

```bash
python -m pytest tests/test_kernel.py -v --tb=short
```

Expected: 所有测试 PASS。

- [ ] **Step 5: 提交**

```bash
git add tain_agent/kernel/pral.py
git commit -m "$(cat <<'EOF'
fix(kernel): wire drive_system weights into system prompt

Store drive_system reference in PRALLoop and append drive weights
(observation, optimization, creation, maintenance) to the system
prompt via _build_prompt(), matching old TaoAgent.run() behavior.
EOF
)"
```

---

### Task 9: 修正 tain 启动器多 agent 行为

**Files:**
- Modify: `tain:34,54`
- Modify: `tain.cmd` (Windows 对应行)

- [ ] **Step 1: 确认当前帮助文本**

```bash
sed -n '34,35p' tain
sed -n '54,55p' tain
```

- [ ] **Step 2: 修改帮助文本和 run 行为**

编辑 `tain`，将第 34 行：
```
  tain run <name>...        启动 agent（多 agent 用空格分隔）
```
改为：
```
  tain run <name>           启动单个 agent（多 agent 启动请用 tain daemon start）
```

将第 54 行 `run` 子命令：
```bash
    run)        exec uv run python main.py $(printf ' --agent %s' "$@") ;;
```
改为（仅取第一个 agent name）：
```bash
    run)        exec uv run python main.py --agent "${1:?missing agent name}" ;;
```

编辑 `tain.cmd`，找到对应的帮助文本行，将 `tain run ^<name^>...        Start agent^(s^)` 改为 `tain run ^<name^>           Start a single agent`。

找到 `:run` 标签，将：
```batch
uv run python main.py --agent %*
```
改为：
```batch
if "%~1"=="" (
    echo missing agent name 1>&2
    exit /b 1
)
uv run python main.py --agent %1
```

- [ ] **Step 3: 运行启动器测试**

```bash
python -m pytest tests/test_tain_script.py -v --tb=short
```

- [ ] **Step 4: 手动验证帮助文本**

```bash
./tain help | head -15
```

Expected: `tain run <name>` 描述中不再提及"多 agent"。

- [ ] **Step 5: 提交**

```bash
git add tain tain.cmd
git commit -m "$(cat <<'EOF'
fix(tain): correct multi-agent help text, limit run to single agent

main.py rejects multiple --agent outside daemon mode. Update launcher
help text and run command to accept a single agent name, matching
actual behavior.
EOF
)"
```

---

### Task 10: 添加热路径写盘 dirty flag 优化

**Files:**
- Modify: `tain_agent/plugins/memory/__init__.py`
- Modify: `tain_agent/plugins/skill/__init__.py`

- [ ] **Step 1: 确认当前 on_cycle_end 和 save 调用**

```bash
grep -n "on_cycle_end\|_save\|_dirty\|add_entity\|add_relation\|register\|practice\|compose" tain_agent/plugins/memory/__init__.py | head -20
grep -n "on_cycle_end\|_save\|_dirty\|register\|practice\|compose" tain_agent/plugins/skill/__init__.py | head -20
```

- [ ] **Step 2: 为 MemoryPlugin 添加 dirty flag**

编辑 `tain_agent/plugins/memory/__init__.py`。在 `__init__` 或 `initialize` 方法中添加 `self._semantic_dirty = False`。

找到 `on_cycle_end` 方法（约第 103 行），确保其中的 save 逻辑受 dirty flag 控制。阅读完整方法后：

将 save 调用从无条件改为：
```python
    def on_cycle_end(self, cycle: int) -> None:
        self._episodic.consolidate()
        if self._semantic_dirty:
            self._semantic.save()
            self._semantic_dirty = False
```

找到 `add_entity` 和 `add_relation` 方法（在 SemanticStore 或 MemoryPlugin 中），在成功添加后设置 dirty：

```python
    def add_entity(self, ...):
        # ... existing logic ...
        self._semantic_dirty = True

    def add_relation(self, ...):
        # ... existing logic ...
        self._semantic_dirty = True
```

- [ ] **Step 3: 为 SkillPlugin 添加 dirty flag**

编辑 `tain_agent/plugins/skill/__init__.py`。在 `__init__` 或 `initialize` 方法中添加 `self._catalog_dirty = False`。

将 `on_cycle_end` 方法（约第 75-76 行）中的：
```python
    def on_cycle_end(self, cycle: int) -> None:
        self._save()
```
改为：
```python
    def on_cycle_end(self, cycle: int) -> None:
        if self._catalog_dirty:
            self._save()
            self._catalog_dirty = False
```

在 `register`、`practice`、`compose` 方法中，成功操作后设置 `self._catalog_dirty = True`。

- [ ] **Step 4: 运行插件测试**

```bash
python -m pytest tests/test_memory_plugin.py tests/test_skill_plugin.py -v --tb=short
```

Expected: 所有测试 PASS。

- [ ] **Step 5: 提交**

```bash
git add tain_agent/plugins/memory/__init__.py tain_agent/plugins/skill/__init__.py
git commit -m "$(cat <<'EOF'
perf(plugins): add dirty-flag gating for semantic and skill catalog writes

Only write semantic.json and skill catalog to disk in on_cycle_end
when data has actually changed (new entities/relations added, skills
registered/practiced/composed). Eliminates unconditional disk writes
on the PRAL hot path.
EOF
)"
```

---

## 最终验证

全部 10 个修复完成后：

```bash
python -m pytest tests/ -q --tb=short 2>&1 | tail -5
```

Expected: `326 passed`（或更多，取决于是否有新测试加入）。

```bash
git log --oneline -10
```

验证提交历史包含全部 10 个修复提交。
