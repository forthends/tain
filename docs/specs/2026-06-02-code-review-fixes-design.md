# 代码审查修复设计

**日期**：2026-06-02
**分支**：`dev`
**来源**：[code-review-dev-vs-main.md](../../report/code-review-dev-vs-main.md)

---

## 概述

基于 `dev` vs `main` 分支代码审查报告中的 10 个发现，在当前 `dev` 分支上逐一修复，每个修复独立提交。修复覆盖 kernel 崩溃、安全漏洞、MCP 协议兼容性、静默错误吞噬、死代码激活、行为退化和效率问题。

---

## 修复设计

### 组 A：Kernel 崩溃修复

#### #1 — PRAL `_perceive()` 签名不匹配

- **文件**：`tain_agent/kernel/pral.py:66`
- **改动**：`mem.recall("recent context", k=5)` → `mem.recall(limit=5)`
- **同步修复**：`kw.query("recent topic")` → `kw.query(limit=5)`，与 KnowledgePlugin 实际签名对齐
- **验证**：`pytest tests/test_kernel.py -v`

#### #2 — TaoAgentCompat 补齐缺失属性

- **文件**：`tain_agent/compat.py`
- **改动**：
  - 添加 `print_state()` 方法，委托给 `kernel.lifecycle.all_health_checks()` 格式化输出
  - 添加 `decision_log` 属性，返回只读空列表
  - 添加 `backend`、`config`、`conversation`、`tools`、`memory`、`goals`、`forge` 属性代理
  - `run()` 中创建的 LLMBackend/ConversationManager/DriveSystem 实例挂到 `self` 上
- **验证**：`pytest tests/test_agent_bundle.py tests/test_ide_kernel.py -v`

---

### 组 B：Web UI 安全修复

#### #3 — Markdown 渲染器 XSS 防护

- **文件**：`webui/render.py:87-89`
- **改动**：在 `_inline_render()` 的链接/图片正则替换前，添加 URL scheme 白名单校验
  - 放行：`http:`、`https:`、`mailto:`、`#`
  - 拦截：`javascript:`、`data:`、`vbscript:` 等，替换为 `#blocked`
  - 对图片 `src` 属性同样适用
- **验证**：`pytest tests/ -k "render" -v`

---

### 组 C：Kernel 健壮性修复

#### #4 — Dispatch.call() 异常处理

- **文件**：`tain_agent/kernel/dispatch.py:28-30`
- **改动**：`except Exception` 块中不再返回 `None`，改为抛出包含异常信息的字符串异常或返回包含错误详情的 dict，使 `PRAL._act()` 能将真实错误信息注入 tool_result 而非通用占位符
- **验证**：`pytest tests/test_kernel.py tests/test_plugin_protocol.py -v`

#### #8 — drive_system 集成

- **文件**：`tain_agent/kernel/pral.py:89`
- **改动**：在 `_build_prompt()` 末尾追加 drive weights 信息（观察/优化/创造/维持分数），对齐旧 `TaoAgent.run()` 的行为
  - 从 `drive_system` 获取各维度权重
  - 格式化为 `[Drive Weights]\nobservation: X.XX | optimization: X.XX | creation: X.XX | maintenance: X.XX`
- **验证**：`pytest tests/test_kernel.py -v`

---

### 组 D：MCP 协议兼容性修复

#### #5 — JSON-RPC 批量请求崩溃

- **文件**：`tain_agent/mcp/server.py:42-48`
- **改动**：在 `_serve_stdio` 的 `json.loads` 之后，检测 `isinstance(req, list)`：
  - 若为列表，对每个元素调用 `_handle_request`，收集非 None 结果，返回 JSON 数组
  - 若为单个对象，保持现有逻辑不变
- **验证**：`pytest tests/test_mcp_server.py -v`

#### #6 — JSON-RPC 位置参数处理

- **文件**：`tain_agent/mcp/server.py:60`
- **改动**：`handler(**params) if isinstance(params, dict) else handler()` → `handler(*params) if isinstance(params, list) else handler(**params)`
- **验证**：`pytest tests/test_mcp_server.py -v`

---

### 组 E：功能修复 + 效率 + UX

#### #7 — 评估插件死代码激活

- **文件**：`tain_agent/plugins/evaluation/__init__.py:106-109`
- **改动**：移除 `evaluate()` 中的 `not plugin_metrics: return None` 守卫，让引擎在空指标集上生成基线快照；在 `_collect_metrics()` 添加 TODO 注释说明需要接入真实指标源
- **验证**：`pytest tests/test_evaluation_plugin.py -v`

#### #9 — tain 启动器多 agent 行为修正

- **文件**：`tain:54`、`tain.cmd`
- **改动**：修改帮助文本，"多 agent 用空格分隔" → "启动单个 agent"；`run` 子命令接受所有位置参数但只取第一个作为 agent name（与其他子命令行为一致）
- **验证**：`pytest tests/test_tain_script.py -v`

#### #10 — 热路径写盘优化

- **文件**：`tain_agent/plugins/memory/__init__.py:103`、`tain_agent/plugins/skill/__init__.py:76`
- **改动**：
  - `MemoryPlugin`：添加 `_semantic_dirty: bool`，`add_entity()`/`add_relation()` 设 True，`on_cycle_end` 仅在 dirty 时 save
  - `SkillPlugin`：添加 `_catalog_dirty: bool`，`register()`/`practice()`/`compose()` 设 True，`on_cycle_end` 仅在 dirty 时 save
- **验证**：`pytest tests/test_memory_plugin.py tests/test_skill_plugin.py -v`

---

## 提交顺序

```
#1  fix(kernel): correct recall/query argument signatures in _perceive()
#2  fix(compat): add missing TaoAgentCompat attributes for --state/--log/--dialogue
#3  fix(webui): block dangerous URL schemes in markdown link rendering
#4  fix(kernel): surface dispatch handler errors instead of swallowing them
#5  fix(mcp): handle JSON-RPC batch requests in stdio server
#6  fix(mcp): support positional (array) params in JSON-RPC dispatch
#7  fix(evaluation): remove dead early-return guard, generate baseline snapshots
#8  fix(kernel): wire drive_system weights into system prompt
#9  fix(tain): correct multi-agent help text, limit run to single agent
#10 perf(plugins): add dirty-flag gating for semantic and skill catalog writes
```

提交遵循 conventional commits 规范，前缀使用 `fix`/`perf`。

---

## 影响范围

| 修复 | 影响文件 | 风险 |
|------|---------|------|
| #1 | `pral.py` | 低，一行改动 |
| #2 | `compat.py` | 中，新增约 40 行代理代码 |
| #3 | `render.py` | 低，添加 URL 白名单 |
| #4 | `dispatch.py` | 低，改变异常处理返回值 |
| #5 | `mcp/server.py` | 低，新增批量请求处理 |
| #6 | `mcp/server.py` | 低，一行改动 |
| #7 | `evaluation/__init__.py` | 低，移除守卫 + 添加注释 |
| #8 | `pral.py` | 低，追加 prompt 文本 |
| #9 | `tain`、`tain.cmd` | 低，帮助文本修改 |
| #10 | `memory/__init__.py`、`skill/__init__.py` | 低，添加 dirty flag |
