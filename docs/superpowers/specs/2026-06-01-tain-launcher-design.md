# Tain 本地启动封装 · 设计文档

**日期**: 2026-06-01
**范围**: 本地启动体验简化（不涉及产品形态分发）
**非目标**: 终端用户打包发布（PyInstaller/.app）—— 留待后续

---

## 1. 背景与目标

### 现状痛点
- 每次启动都要 `source .venv/bin/activate`（或 `pip install -e .`）
- 直接 `python main.py` 容易在错误环境下运行（system Python、缺包）
- Web UI 启动流程散落在 README、Makefile、Dockerfile 三个地方
- Makefile 的 `make run NAME=poet` 仍是开发风格，不直观

### 目标
一个 `./tain` 命令覆盖 90% 日常使用：
- 不需要 `source` 任何虚拟环境
- 首次运行自动同步依赖，后续毫秒级启动
- 子命令风格（`tain run poet` / `tain webui`），与 `python main.py` 旧用法兼容
- macOS / Linux / Windows 三平台一致

### 非目标
- 不打 PyInstaller 二进制（产品形态分发）
- 不重写 `main.py` 的 argparse
- 不引入新依赖管理工具（继续用 `uv`）
- 不改 Makefile 的 `test`/`clean` 目标

---

## 2. 架构

新增 2 个文件，**零 Python 代码改动**：

```
tain/
├── tain              # POSIX shell 启动器（macOS/Linux）
├── tain.cmd          # Windows cmd 批处理启动器
├── Makefile          # 追加转发规则；test/clean 不变
├── README.md         # Quick Start 改写为先介绍 ./tain
└── ...               # 其他文件不动
```

**职责**：`tain` 脚本是**纯转发层** —— 子命令→main.py 参数的映射在 shell 里完成，main.py 的 argparse 仍是真权威。零 Python 改动意味着 main.py 的 326 个测试零回归。

### 启动流程

```
./tain run poet
    │
    ▼
  tain.sh 解析子命令
    │
    ├─ uv 已装？  ──否──→ 打印安装指引，exit 127
    │
    ├─ .venv 就绪？(检查 .venv/.synced 时间戳 vs uv.lock)
    │     │
    │     否 → uv sync --frozen
    │     │     │
    │     ▼     ▼
    │   touch .venv/.synced
    │
    ▼
  exec uv run python main.py --agent poet
    │
    ▼
  现有 main.py 入口（不变）
```

**幂等保证**：
- `uv sync --frozen` 严格遵守 `uv.lock`，不修改任何依赖
- `.venv/.synced` 时间戳只在 sync 成功后更新
- 二次启动跳过 sync，`uv run` 走已就绪的 `.venv`，~200ms 启动

---

## 3. 命令映射

| 子命令 | 实际调用 | 说明 |
|---|---|---|
| `tain` (无参) / `tain help` | — | 打印内置帮助（子命令列表） |
| `tain run <name...>` | `uv run python main.py --agent <name>` | 启动 agent（多 agent 用空格分隔） |
| `tain new` | `uv run python main.py --create-agent` | 交互式创建向导 |
| `tain list` | `uv run python main.py --list-agents` | 列出所有 agent |
| `tain state <name>` | `uv run python main.py --agent <name> --state` | 打印 agent 状态 |
| `tain log <name>` | `uv run python main.py --agent <name> --log` | 查看决策日志 |
| `tain export <name>` | `uv run python main.py --agent <name> --export` | 导出为独立包 |
| `tain dialogue <name>` | `uv run python main.py --agent <name> --dialogue` | REPL 对话模式 |
| `tain webui [port]` | `uv run python main.py --webui --port <port>` | 启动 Web UI（默认 8000）+ 1.5s 后自动开浏览器 |
| `tain daemon <op> <name>` | `uv run python main.py --daemon --<op> --agent <name>` | 守护进程管理（op: start/stop/status） |
| `tain reset` | `rm -rf .venv` | 删除 .venv（下次启动自动重 sync） |
| `tain --agent <name>` ... | 透传给 main.py | 未识别子命令且像 main.py flag 时透传 |
| 其他 | — | 打印错误 + 提示 `tain help` |

### 错误处理

- **uv 缺失**：打印安装指引，exit 127
  ```
  ✗ 未找到 uv。请先安装：
    macOS:  brew install uv
    Linux:  curl -LsSf https://astral.sh/uv/install.sh | sh
    Windows: winget install astral-sh.uv
  ```
- **.venv 损坏**：`tain reset` 重置
- **main.py 报错**：原样透传退出码与 stderr
- **未知子命令**：exit 1，提示运行 `tain help`
- **uv sync 失败**：透传 uv 错误，提示网络或权限问题

### `tain webui` 自动开浏览器

后台 1.5s 后执行：
- macOS：`open "http://localhost:${port}"`
- Linux：`xdg-open "http://localhost:${port}"`（fallback 到提示）
- Windows：`start "" "http://localhost:${port}"`

失败（headless 服务器、无浏览器）静默忽略，不影响 webui 启动。

---

## 4. 关键脚本

### `tain`（POSIX shell，目标 ~80 行）

```bash
#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

if ! command -v uv >/dev/null 2>&1; then
    echo "✗ 未找到 uv。请先安装：" >&2
    echo "  macOS:   brew install uv" >&2
    echo "  Linux:   curl -LsSf https://astral.sh/uv/install.sh | sh" >&2
    exit 127
fi

needs_sync() {
    [ ! -d ".venv" ] && return 0
    [ ! -f ".venv/.synced" ] && return 0
    [ "uv.lock" -nt ".venv/.synced" ] && return 0
    return 1
}

if needs_sync; then
    echo "→ 首次启动或 lockfile 变更，同步依赖（~30s）…"
    uv sync --frozen
    touch ".venv/.synced"
fi

cmd="${1:-help}"
[ $# -gt 0 ] && shift

case "$cmd" in
    run)        exec uv run python main.py --agent "$@" ;;
    new)        exec uv run python main.py --create-agent ;;
    list)       exec uv run python main.py --list-agents ;;
    state)      exec uv run python main.py --agent "$1" --state ;;
    log)        exec uv run python main.py --agent "$1" --log ;;
    export)     exec uv run python main.py --agent "$1" --export ;;
    dialogue)   exec uv run python main.py --agent "$1" --dialogue ;;
    webui)
        port="${1:-8000}"
        (sleep 1.5 && open "http://localhost:${port}" 2>/dev/null || \
                       xdg-open "http://localhost:${port}" 2>/dev/null || true) &
        exec uv run python main.py --webui --port "$port" ;;
    daemon)
        op="${1:?usage: tain daemon <start|stop|status> <name>}"
        name="${2:?missing agent name}"
        exec uv run python main.py --daemon "--${op}" --agent "$name" ;;
    reset)      rm -rf .venv && echo "✓ 已重置 .venv" ;;
    help|-h|--help) print_help ;;
    --agent|--create-agent|--list-agents|--webui|--daemon|--state|--log|--export)
        exec uv run python main.py "$cmd" "$@" ;;
    *)
        echo "✗ 未知子命令：$cmd" >&2
        echo "  运行 'tain help' 查看用法" >&2
        exit 1
        ;;
esac
```

### `tain.cmd`（Windows 批处理，目标 ~50 行）

逻辑同上，语法转 cmd 风格（`if "%X%"=="Y"`、`goto` 分派、`%*` 转参）。两份脚本功能等价，分别测试。

### Makefile 集成（追加，不替换）

```makefile
tain:
	./tain $(filter-out $@,$(MAKECMDGOALS))
	@true

tain-%:
	./tain $(subst tain-,,$@) $(filter-out $@,$(MAKECMDGOALS))
	@true

# 现有 test/clean/run/webui 目标保留不动
```

支持 `make tain-run NAME=poet` → 实际调用 `./tain run poet`，并兼容 `make tain webui` 等子命令模式。

---

## 5. 测试

### 冒烟测试（新增 `tests/test_tain_script.py`，目标 ~50 行）

```python
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

def test_tain_help():
    r = subprocess.run(["./tain", "help"], cwd=REPO_ROOT, capture_output=True, text=True)
    assert r.returncode == 0
    for cmd in ["run", "new", "list", "webui", "state", "log", "export", "daemon", "reset"]:
        assert cmd in r.stdout

def test_tain_unknown_subcommand():
    r = subprocess.run(["./tain", "totally-fake"], cwd=REPO_ROOT, capture_output=True, text=True)
    assert r.returncode != 0
    assert "未知子命令" in r.stderr or "tain help" in r.stderr

def test_tain_passthrough_to_main():
    """未识别 flag 直接透传给 main.py"""
    r = subprocess.run(["./tain", "--list-agents"], cwd=REPO_ROOT, capture_output=True, text=True)
    # main.py 接受 --list-agents 且正常执行（无 agent 时输出空表）
    assert r.returncode == 0
```

### 手动验证清单（提交前 5 项）

1. 干净 clone → `./tain run test-agent` 触发首次 sync，agent 启动
2. 二次运行 `./tain run test-agent` 跳过 sync，~200ms 启动
3. `./tain webui` 启动 uvicorn + 浏览器自动打开 localhost:8000
4. `./tain list` / `./tain state test-agent` 正常
5. `./tain --agent test-agent --state` 透传仍可用

### 回归

- `make test` 现有 326 用例必须全过（main.py 零改动，理论零风险）
- 不引入新依赖

---

## 6. 文档

仅改 `README.md`：

### 改动清单

1. **Quick Start**（第 14–37 行）整段重写：
   ```bash
   # 1. 装 uv（一次）
   brew install uv   # macOS
   # Linux:  curl -LsSf https://astral.sh/uv/install.sh | sh
   # Windows: winget install astral-sh.uv

   # 2. 启动
   ./tain run poet
   ./tain webui      # 自动打开浏览器
   ```

2. **CLI Reference** 表格（第 240–254 行）加 `tain` 列；旧 `python main.py` 行保留并标注「旧用法」

3. **新增小节** `### 安装 uv`（约 Quick Start 之前）

### 不改

- 架构图、配置说明、API 文档等其他章节
- `docs/architecture.md`、`docs/quickstart.md`（`quickstart.md` 视为 Quick Start 的展开版，未来可选择性同步）

---

## 7. 风险与权衡

| 风险 | 缓解 |
|---|---|
| WebUI 的 Tailwind CSS 未构建 → 页面无样式 | 不在本次范围；旧路径同样有此问题。已知问题独立处理 |
| Windows cmd 脚本的引号转义陷阱 | cmd 脚本独立测试，subcommand 透传用 `%*` 而不是逐参 |
| 用户在子目录执行 `./tain` | 用 `BASH_SOURCE` / `%~dp0` 定位脚本所在目录，强制 cd |
| Makefile 的 `tain-%` 模式吃掉 `tain-run` 等真实目标 | Makefile 模式只匹配字面 `tain` 和 `tain-<word>`，不会冲突 |
| `uv run` 性能开销 | 实测 200ms 以内，可接受；如需更极致可缓存 `PYTHONPATH` 环境变量（不必要） |

---

## 8. 实施顺序

1. 写 `tain`（POSIX）+ 内置 help 文本
2. 写 `tests/test_tain_script.py` + 跑通
3. 写 `tain.cmd`（Windows）
4. 改 Makefile（追加 `tain` / `tain-%` 规则）
5. 改 README.md Quick Start + CLI Reference + 安装 uv 小节
6. 手动跑 5 项验证清单
7. `make test` 全过
8. 提交

预计总工作量：脚本 + 测试 + 文档 ≈ 200–250 行新增，0 行删除。
