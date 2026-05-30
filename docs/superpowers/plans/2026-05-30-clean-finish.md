# 收尾迭代 (Clean Finish) · 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 清完审查报告全部 P2 债务（ProcessManager 抽象 + MAX_CYCLES 修正），修复 12 个遗留测试失败

**Architecture:** 两个独立工作流 — F.ProcessManager 抽象封装 8 处 subprocess.run() 调用；G.测试修复让全量测试通过

**Tech Stack:** Python 3.12+, subprocess, pytest, FastAPI

---

### 工作流 F · ProcessManager 抽象

### Task F1: 创建 ProcessManager

**Files:**
- Create: `webui/process.py`

- [ ] **Step 1: 创建 `webui/process.py`**

```python
"""Agent process lifecycle manager — unified subprocess interface."""
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path


@dataclass
class ProcessResult:
    success: bool
    stdout: str
    stderr: str
    returncode: int


class ProcessManager:
    """Manages agent process start/stop/restart via supervise_agent.py."""

    def __init__(self, project_root: str | None = None):
        if project_root is None:
            project_root = str(Path(__file__).resolve().parent.parent)
        self._supervisor = str(Path(project_root) / "supervise_agent.py")

    def _run(self, args: list[str], timeout: float = 30.0) -> ProcessResult:
        result = subprocess.run(
            [sys.executable, self._supervisor, *args],
            capture_output=True, text=True, timeout=timeout,
        )
        return ProcessResult(
            success=result.returncode == 0,
            stdout=result.stdout.strip(),
            stderr=result.stderr.strip(),
            returncode=result.returncode,
        )

    def start(self, agent_name: str) -> ProcessResult:
        return self._run(["--agent-name", agent_name, "--daemon", "--"])

    def stop(self, agent_name: str) -> ProcessResult:
        return self._run(["--agent-name", agent_name, "--stop"])

    def restart(self, agent_name: str, wait: float = 1.0) -> tuple[ProcessResult, ProcessResult]:
        stop_result = self.stop(agent_name)
        time.sleep(wait)
        start_result = self.start(agent_name)
        return stop_result, start_result

    def status(self, agent_name: str) -> ProcessResult:
        return self._run(["--agent-name", agent_name, "--status"])
```

- [ ] **Step 2: 编译验证**

```bash
python3 -m py_compile webui/process.py && echo "OK"
```

- [ ] **Step 3: 提交**

```bash
git add webui/process.py
git commit -m "feat: add ProcessManager for agent lifecycle management (P2-16)"
```

---

### Task F2: 更新 api_agents.py 使用 ProcessManager

**Files:**
- Modify: `webui/routes/api_agents.py:83-125`

- [ ] **Step 1: 读取当前文件内容**

```bash
grep -n "import subprocess\|supervisor\|subprocess.run" webui/routes/api_agents.py
```

- [ ] **Step 2: 替换 start/stop/restart 三个端点**

在 `webui/routes/api_agents.py` 顶部添加导入：

```python
from webui.process import ProcessManager
```

修改 `api_agent_start`（行 83-91 附近）：

```python
@router.post("/agent/{name}/start")
async def api_agent_start(name: str):
    result = ProcessManager().start(name)
    return {"success": result.success, "output": result.stdout, "error": result.stderr}
```

修改 `api_agent_stop`（行 94-102 附近）：

```python
@router.post("/agent/{name}/stop")
async def api_agent_stop(name: str):
    result = ProcessManager().stop(name)
    return {"success": result.success, "output": result.stdout, "error": result.stderr}
```

修改 `api_agent_restart`（行 105-125 附近）：

```python
@router.post("/agent/{name}/restart")
async def api_agent_restart(name: str):
    stop_result, start_result = ProcessManager().restart(name)
    return {
        "success": start_result.success,
        "stop_output": stop_result.stdout,
        "output": start_result.stdout,
        "error": start_result.stderr,
    }
```

注意：移除这三个端点中内联的 `import subprocess, sys, time` 和手工 `supervisor` 路径解析代码。

- [ ] **Step 3: 编译验证**

```bash
python3 -m py_compile webui/routes/api_agents.py && echo "OK"
```

- [ ] **Step 4: 确认无残留 subprocess 导入**

```bash
grep -n "import subprocess\|from subprocess" webui/routes/api_agents.py
```

如果 start/stop/restart 端点已无 `import subprocess`，但 `api_create_agent` 或其他端点可能仍有自己的 subprocess 调用（非 supervisor 相关），不应误删。

- [ ] **Step 5: 提交**

```bash
git add webui/routes/api_agents.py
git commit -m "refactor: use ProcessManager in api_agents.py routes (P2-16)"
```

---

### Task F3: 更新 pages.py 使用 ProcessManager

**Files:**
- Modify: `webui/routes/pages.py:278-330`

- [ ] **Step 1: 读取当前 controls 端点**

```bash
grep -n "controls/start\|controls/stop\|controls/restart\|subprocess.run\|import subprocess" webui/routes/pages.py
```

- [ ] **Step 2: 添加导入，替换三个 controls 端点**

在 `webui/routes/pages.py` 顶部已有导入区域添加：

```python
from webui.process import ProcessManager
```

修改 `agent_control_start`（行 278-293 附近）：

```python
@router.post("/agent/{name}/controls/start", response_class=HTMLResponse)
async def agent_control_start(request: Request, name: str):
    ProcessManager().start(name)
    import time
    time.sleep(0.5)
    agent = get_agent(name)
    resp = _render("components/agent_controls.html", {
        "request": request, "agent": agent or {"name": name, "status": "unknown"},
    })
    resp.headers["HX-Trigger"] = "agentStatusChanged"
    return resp
```

修改 `agent_control_stop`（行 296-311 附近）：

```python
@router.post("/agent/{name}/controls/stop", response_class=HTMLResponse)
async def agent_control_stop(request: Request, name: str):
    ProcessManager().stop(name)
    import time
    time.sleep(0.5)
    agent = get_agent(name)
    resp = _render("components/agent_controls.html", {
        "request": request, "agent": agent or {"name": name, "status": "unknown"},
    })
    resp.headers["HX-Trigger"] = "agentStatusChanged"
    return resp
```

修改 `agent_control_restart`（行 314-330 附近）：

```python
@router.post("/agent/{name}/controls/restart", response_class=HTMLResponse)
async def agent_control_restart(request: Request, name: str):
    ProcessManager().restart(name)
    agent = get_agent(name)
    resp = _render("components/agent_controls.html", {
        "request": request, "agent": agent or {"name": name, "status": "unknown"},
    })
    resp.headers["HX-Trigger"] = "agentStatusChanged"
    return resp
```

注意：`controls/start` 和 `controls/stop` 中的 `time.sleep(0.5)` 保留在路由层——这是 HTMX 触发的 UI 等待，不是进程管理逻辑。`controls/restart` 的 sleep 已封装在 `ProcessManager.restart()` 中。

- [ ] **Step 3: 编译验证**

```bash
python3 -m py_compile webui/routes/pages.py && echo "OK"
```

- [ ] **Step 4: 确认无残留内联 subprocess 导入**

```bash
grep -n "import subprocess\|from subprocess" webui/routes/pages.py
```

controls 端点中的内联 `import subprocess, sys` 应已移除。其他端点中如有独立的 subprocess 调用（非 supervisor 相关）不应误删。

- [ ] **Step 5: 提交**

```bash
git add webui/routes/pages.py
git commit -m "refactor: use ProcessManager in pages.py controls routes (P2-16)"
```

---

### 工作流 G · 收尾 + 测试修复

### Task G1: 修正 MAX_CYCLES

**Files:**
- Modify: `tain_agent/core/agent.py:60`

- [ ] **Step 1: 修改变量定义**

`tain_agent/core/agent.py` 第 60 行：

```python
# 旧:
MAX_CYCLES = {"explore": 10, "work": 999999}

# 新:
MAX_CYCLES = {"explore": 10, "work": float("inf")}
```

- [ ] **Step 2: 编译验证**

```bash
python3 -m py_compile tain_agent/core/agent.py && echo "OK"
```

- [ ] **Step 3: 提交**

```bash
git add tain_agent/core/agent.py
git commit -m "fix: use float('inf') instead of 999999 for work phase max cycles (P2-18)"
```

---

### Task G2: 修复命令执行测试（10 个）

**Files:**
- Modify: `tests/test_background_manager.py`
- Modify: `tests/test_templates.py`

**根因**: H2 修复将 `_async_start` 中的 `create_subprocess_shell` 改为 `create_subprocess_exec(*shlex.split(command))`，以及 `run_shell` 中 `shell=True` 改为 `shlex.split()` + `shell=False`。复合 shell 命令（含 `&&`、`|`、`>`）必须以 `bash -c "..."` 形式执行。

- [ ] **Step 1: 查看当前测试失败详情**

```bash
.venv/bin/python -m pytest tests/test_background_manager.py tests/test_templates.py::TestRunShell -v --tb=short 2>&1 | tail -40
```

- [ ] **Step 2: 修复 test_background_manager.py 中使用复合命令的测试**

需要修复的测试用例（使用 `&&` 连接的命令）：

`test_start_command_with_output`（行 35）：
```python
# 旧:
result = mgr.start("echo line1 && sleep 0.3 && echo line2")

# 新:
result = mgr.start("bash -c 'echo line1 && sleep 0.3 && echo line2'")
```

`test_get_output`（行 50）：
```python
# 旧:
result = mgr.start("echo output_line_1 && sleep 0.3 && echo output_line_2")

# 新:
result = mgr.start("bash -c 'echo output_line_1 && sleep 0.3 && echo output_line_2'")
```

其他测试（`test_kill_process`、`test_wait_with_timeout`、`test_kill_all`、`test_list_processes`、`test_max_processes_limit`）中的命令若为简单命令（如 `sleep 30`、`echo hello`），`shlex.split()` 后应能正常执行。若失败，逐个诊断：

- 如果 `echo hello` 失败：可能系统上 `echo` 的 PATH 查找行为变化，改为 `/bin/echo hello` 或 `bash -c 'echo hello'`
- 如果 `sleep 30` 失败：检查 `preexec_fn` 在 `create_subprocess_exec` 中是否被拒绝

对于模块级单例测试 `test_bg_start_uses_manager`（`TestModuleLevelSingleton`）：

```python
# 检查 bg_start 工具函数传递的命令格式
# bg_start 内部调用 manager.start(command)，最终走到 _async_start
# 如果测试传入简单命令如 "echo test"，改为 "bash -c 'echo test'" 作为保守处理
```

- [ ] **Step 3: 修复 test_templates.py 的 test_failing_command**

当前测试（行 78-81）：

```python
def test_failing_command(self):
    result = run_shell("exit 1")
    assert result["success"] is False
    assert result["exit_code"] == 1
```

`exit` 是 shell 内建命令，`shlex.split("exit 1")` 会变成 `["exit", "1"]`，`subprocess.run` 找不到 `exit` 可执行文件（`FileNotFoundError`）。

修复：将命令改为使用 `bash -c`：

```python
def test_failing_command(self):
    result = run_shell("bash -c 'exit 1'")
    assert result["success"] is False
    assert result["exit_code"] == 1
```

或者改用一定会失败的非零退出码命令：

```python
def test_failing_command(self):
    result = run_shell("bash -c 'exit 1'")
    assert result["success"] is False
    assert result["exit_code"] == 1
```

- [ ] **Step 4: 运行修复后的测试**

```bash
.venv/bin/python -m pytest tests/test_background_manager.py tests/test_templates.py::TestRunShell -v --tb=short
```

目标：10 个测试全部通过。

- [ ] **Step 5: 提交**

```bash
git add tests/test_background_manager.py tests/test_templates.py
git commit -m "test: fix command execution tests for shlex.split() behavior"
```

---

### Task G3: 修复 Token 估算测试（2 个）

**Files:**
- Modify: `tests/test_token_utils.py:16-18`
- Modify: `tests/test_templates.py:114-116`

- [ ] **Step 1: 修复 test_token_utils.py**

第 16-18 行：

```python
# 旧:
def test_longer_text(self):
    est = estimate_tokens("x" * 1000)
    assert est > 400

# 新:
def test_longer_text(self):
    text = "x" * 1001  # 1001 chars × 2/5 ≈ 400.4 → at least 401 tokens with estimator
    est = estimate_tokens(text)
    assert est > 400
```

- [ ] **Step 2: 运行验证**

```bash
.venv/bin/python -m pytest tests/test_token_utils.py::TestEstimateTokens::test_longer_text -v
```

预期：PASS

- [ ] **Step 3: 修复 test_templates.py**

第 114-116 行（TestEstimateTokens 类中）：

```python
# 旧:
def test_longer_text(self):
    est = estimate_tokens("Hello " * 800)
    assert est > 400

# 新:
def test_longer_text(self):
    text = "Hello " * 801  # 4005 chars × 2/5 ≈ 1602 tokens
    est = estimate_tokens(text)
    assert est > 400
```

- [ ] **Step 4: 运行验证**

```bash
.venv/bin/python -m pytest tests/test_templates.py::TestEstimateTokens::test_longer_text -v
```

预期：PASS

- [ ] **Step 5: 提交**

```bash
git add tests/test_token_utils.py tests/test_templates.py
git commit -m "test: fix token estimate off-by-one assertions for new chars*2/5 formula"
```

---

## 最终验证

```bash
.venv/bin/python -m pytest tests/ -q --tb=short 2>&1 | tail -5
```

目标：`0 failed`（12 个遗留失败全部修复）。

---

## 任务依赖

```
F1 ── F2 ── F3     (ProcessManager → 两处路由替换)
G1                  (独立)
G2 ── G3            (可并行)
```

F 系列和 G 系列完全独立，可并行执行。G1/G2/G3 互不依赖，也可并行。
