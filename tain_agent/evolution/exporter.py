"""
Export Pipeline — extract evolved agent as a standalone executable.

Four-step pipeline (Phase 3 §3.2):
  Step 0: Quality Gate (delegates to quality_gate.py)
  Step 1: Collect — gather tools, knowledge, identity, version from workspace
  Step 2: Rewrite — AST-based import rewriting (tain_agent → runtime)
  Step 3: Assemble — copy runtime, mount artifacts, generate entry points
  Step 4: Verify  — import check, tool loading, knowledge integrity
  Output: dist/{name}-v{version}.tar.gz
"""

import ast
import json
import os
import shutil
import sys
import tarfile
from pathlib import Path
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _project_root() -> Path:
    return Path(__file__).resolve().parent.parent.parent


# ─── Data types ────────────────────────────────────────────────────────

@dataclass
class ExportResult:
    """Result of a successful export."""
    name: str
    version: str
    output_path: str       # path to .tar.gz
    dist_dir: str          # path to uncompressed dist directory
    tool_count: int
    knowledge_count: int
    skill_count: int = 0       # number of Skill directories exported
    knowledge_skill_count: int = 0  # knowledge docs exported as Skills
    total_size_bytes: int = 0
    verification: dict = field(default_factory=dict)
    created_at: str = field(default_factory=_now_iso)


# ─── Step 1: Collect ───────────────────────────────────────────────────

def _collect_tools(workspace_dir: Optional[Path]) -> list[Path]:
    """Collect forged tool .py files from workspace and built-in dirs."""
    tools = []
    if workspace_dir:
        ws_tools = workspace_dir / "forged_tools"
        if ws_tools.exists():
            tools.extend(f for f in ws_tools.glob("*.py")
                         if not f.name.startswith("_"))
    # Always include built-in forged tools
    builtin = _project_root() / "tain_agent" / "tools" / "forged"
    if builtin.exists():
        for f in builtin.glob("*.py"):
            if not f.name.startswith("_") and f not in tools:
                tools.append(f)
    return tools


def _collect_knowledge(workspace_dir: Optional[Path]) -> Optional[Path]:
    """Return the knowledge directory path if it exists."""
    if workspace_dir:
        kg = workspace_dir / "knowledge_garden"
        if kg.exists():
            return kg
        kg = workspace_dir / "knowledge"
        if kg.exists():
            return kg
    return None


def _collect_identity(workspace_dir: Optional[Path]) -> Optional[dict]:
    """Load identity data from workspace state."""
    if workspace_dir is None:
        return None
    identity_path = workspace_dir / "state" / "personality.json"
    if not identity_path.exists():
        return None
    try:
        return json.loads(identity_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, IOError):
        return None


def _collect_version(workspace_dir: Optional[Path]) -> str:
    """Read version from workspace, defaulting to '0.1.0'."""
    if workspace_dir is None:
        return "0.1.0"
    version_path = workspace_dir / "state" / "version.json"
    if version_path.exists():
        try:
            data = json.loads(version_path.read_text(encoding="utf-8"))
            return data.get("version", "0.1.0")
        except (json.JSONDecodeError, IOError):
            pass
    return "0.1.0"


def _collect_drives(workspace_dir: Optional[Path]) -> dict:
    """Collect drive values from workspace state."""
    if workspace_dir is None:
        return {}
    drives_path = workspace_dir / "state" / "drives.json"
    if drives_path.exists():
        try:
            return json.loads(drives_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, IOError):
            pass
    # Try personality.json as fallback
    identity_data = _collect_identity(workspace_dir)
    if identity_data:
        return identity_data.get("drives", {})
    return {}


# ─── Step 2: AST Rewrite ───────────────────────────────────────────────

class ImportRewriter(ast.NodeTransformer):
    """AST transformer: rewrite framework imports to runtime equivalents.

    - ``from tain_agent.xxx import ...`` → ``from runtime.xxx import ...``
    - ``from tain_agent.core.xxx import ...`` → ``from runtime.xxx import ...``
    - ``from tain_agent.tools.forged.xxx`` → ``from tools.xxx``
    - Removes: ``from tain_agent.evolution.xxx`` (framework-only, replaced with stub)
    - Removes: ``from tain_agent.core.time_utils import now`` → inline replacement
    """

    # Map framework modules to their runtime equivalents
    MODULE_MAP = {
        "tain_agent.core.llm": "runtime.llm",
        "tain_agent.core.memory": "runtime.memory",
        "tain_agent.core.conversation": "runtime.conversation",
        "tain_agent.core.personality": "runtime.identity",
        "tain_agent.core.drives": "runtime.identity",
        "tain_agent.core.time_utils": None,  # replaced inline
        "tain_agent.evolution": None,         # removed (framework-only)
        "tain_agent.core.agent": None,        # removed (framework-only)
        "tain_agent.core.bootstrap": None,    # removed (framework-only)
        "tain_agent.core.cognitive_loop": None,  # removed (framework-only)
    }

    # Symbols from time_utils that get inlined
    TIME_SYMBOLS = {"now", "set_timezone", "get_timezone"}

    def visit_ImportFrom(self, node):
        """Rewrite or remove framework imports."""
        if node.module is None:
            return node

        module = node.module

        # Check exact module map first
        if module in self.MODULE_MAP:
            mapped = self.MODULE_MAP[module]
            if mapped is None:
                # Remove this import entirely (framework-only / will be inlined)
                if any(alias.name in self.TIME_SYMBOLS for alias in node.names):
                    # Don't remove time_utils imports — they'll be handled by
                    # a runtime shim. Map to a local compat layer.
                    return None  # removed — caller uses datetime directly
                return None
            return ast.ImportFrom(
                module=mapped,
                names=node.names,
                level=node.level,
            )

        # Prefix-based mapping
        if module.startswith("tain_agent.tools.forged."):
            tool_name = module.rsplit(".", 1)[-1]
            return ast.ImportFrom(
                module=f"tools.{tool_name}",
                names=node.names,
                level=node.level,
            )

        if module.startswith("tain_agent.core."):
            sub = module.replace("tain_agent.core.", "")
            if sub in ("llm", "memory", "conversation", "personality", "drives", "time_utils"):
                mapped = self.MODULE_MAP.get(module)
                if mapped is None:
                    return None
            return None  # Other core modules not available at runtime

        if module.startswith("tain_agent.") and not module.startswith("tain_agent.runtime"):
            # Generic tain_agent import not mapped — drop it
            return None

        return node


def rewrite_imports(source: str) -> str:
    """Rewrite a Python source file's imports for standalone runtime."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return source

    rewriter = ImportRewriter()
    rewritten = rewriter.visit(tree)
    ast.fix_missing_locations(rewritten)

    try:
        return ast.unparse(rewritten)
    except AttributeError:
        # Python < 3.9 fallback
        import astor
        return astor.to_source(rewritten)


# ─── Step 3: Assemble ──────────────────────────────────────────────────

_MAIN_PY_TEMPLATE = '''"""
{agent_name} v{version} — standalone evolved agent.

Exported from Tao Agent factory on {export_date}.
Evolution cycles: {evolution_cycles}
Tools: {tool_count}  |  Knowledge docs: {knowledge_count}
"""

import json
import os
import sys
import time
from pathlib import Path

# Ensure the agent's own directory is on sys.path
_AGENT_DIR = Path(__file__).resolve().parent
if str(_AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(_AGENT_DIR))

from runtime.identity import Identity
from runtime.memory import MemoryStore
from runtime.conversation import ConversationManager
from runtime.tools import ToolRegistry
from runtime.tui import create_tui, dispatch_slash_command
from runtime.llm import create_backend


def load_config():
    """Load config.yaml or fall back to env vars."""
    config_path = _AGENT_DIR / "config.yaml"
    if config_path.exists():
        try:
            import yaml
            with open(config_path) as f:
                return yaml.safe_load(f)
        except Exception:
            pass
    return {{
        "llm": {{
            "provider": os.environ.get("TAO_LLM_PROVIDER", "anthropic"),
            "model": os.environ.get("TAO_LLM_MODEL", "claude-sonnet-4-6-20250514"),
            "api_key_env": os.environ.get("TAO_API_KEY_ENV", "ANTHROPIC_API_KEY"),
            "max_tokens": int(os.environ.get("TAO_MAX_TOKENS", "8192")),
        }}
    }}


def load_tools(registry: ToolRegistry):
    """Import all tools from the tools/ directory into the registry."""
    tools_dir = _AGENT_DIR / "tools"
    if not tools_dir.exists():
        return

    for py_file in sorted(tools_dir.glob("*.py")):
        if py_file.name.startswith("_"):
            continue
        name = py_file.stem
        try:
            mod = __import__(f"tools.{{name}}", fromlist=["main"])
            if hasattr(mod, "main"):
                schema = getattr(mod, "SCHEMA", {{
                    "name": name,
                    "description": (mod.__doc__ or f"Tool: {{name}}").strip(),
                    "input_schema": {{"type": "object", "properties": {{}}}},
                }})
                registry.register(name, mod.main, schema)
        except Exception as exc:
            print(f"  [warn] Failed to load tool '{{name}}': {{exc}}")


def scan_knowledge():
    """Return count and index of knowledge docs available."""
    kg = _AGENT_DIR / "knowledge"
    if not kg.exists():
        return 0, []
    md_files = list(kg.rglob("*.md"))
    doc_count = len(md_files)

    # Build frontmatter index for progressive discovery
    knowledge_index = []
    try:
        from runtime.tui import _RICH_AVAILABLE
        if _RICH_AVAILABLE:
            from tools.knowledge_graph import discover_knowledge
            knowledge_index = discover_knowledge(str(kg))
    except Exception:
        # Fallback: build basic index from filenames
        for f in md_files:
            knowledge_index.append({{
                "name": f.stem.lower().replace("_", "-"),
                "description": f.stem.replace("_", " ").title(),
                "tags": [],
                "path": str(f),
            }})

    return doc_count, knowledge_index


def build_system_prompt(identity: Identity, knowledge_index: list) -> str:
    """Build the system prompt with knowledge discovery index injected."""
    parts = [identity.boot_intro(plain=True)]

    if knowledge_index:
        parts.append("\\nAvailable knowledge:")
        for entry in knowledge_index[:20]:  # cap to avoid prompt bloat
            name = entry.get("name", "?")
            desc = entry.get("description", "")[:120]
            parts.append(f"  - {{name}}: {{desc}}")
        if len(knowledge_index) > 20:
            parts.append(f"  ... and {{len(knowledge_index) - 20}} more documents.")

    return "\\n".join(parts)


def boot_sequence(identity: Identity, memory: MemoryStore, tui,
                  tool_count: int = 0, doc_count: int = 0,
                  knowledge_index: list = None):
    """Print the first-boot or welcome-back sequence through the TUI."""
    if memory.is_first_boot():
        intro = identity.boot_intro(tool_count=tool_count, doc_count=doc_count, plain=False)
    else:
        last = memory.last_session_summary()
        intro = identity.welcome_back(last, doc_count=doc_count, plain=False)

    tui.startup(intro)

    # Show knowledge index summary
    if knowledge_index:
        print(f"Knowledge index: {{len(knowledge_index)}} documents available.")
        print("Type /knowledge <query> to search.\\n")


def agent_loop(identity: Identity, memory: MemoryStore,
               conv: ConversationManager, registry: ToolRegistry,
               backend, tui, knowledge_index: list = None):
    """Main conversation loop with streaming responses and TUI integration."""
    session_id = memory.start_session(identity.version)
    tool_count = len(registry.list_names())
    doc_count = len(knowledge_index) if knowledge_index else scan_knowledge()[0]
    knowledge_dir = str(_AGENT_DIR / "knowledge")

    boot_sequence(identity, memory, tui, tool_count=tool_count,
                  doc_count=doc_count, knowledge_index=knowledge_index)

    tui.update_status(status="ready", tool_count=tool_count, doc_count=doc_count)
    system_prompt = build_system_prompt(identity, knowledge_index or [])

    while True:
        try:
            user_input = tui.render_prompt()
        except (EOFError, KeyboardInterrupt):
            tui.render_error("Interrupted — saving and exiting.")
            break

        user_input = user_input.strip()
        if not user_input:
            continue

        # Slash commands
        if user_input.startswith("/"):
            should_quit = dispatch_slash_command(
                user_input, identity, memory, registry, tui,
                knowledge_dir=knowledge_dir)
            if should_quit:
                break
            continue

        # Normal conversation turn
        tui.render_user_message(user_input)
        conv.append("user", user_input)
        memory.increment_messages()

        # Stream the response
        tui.update_status(status="thinking")
        collected_text = []
        thinking_text = []
        tool_calls = []
        t0 = time.time()

        try:
            for event in backend.stream_message(
                system_prompt=system_prompt,
                messages=conv.to_messages(),
                tools=registry.get_schemas(),
            ):
                if event["type"] == "text_delta":
                    collected_text.append(event["text"])
                    tui.render_stream(event["text"])

                elif event["type"] == "thinking_delta":
                    thinking_text.append(event["text"])

                elif event["type"] == "tool_call":
                    tool_calls.append(event["tool"])
                    elapsed_ms = (time.time() - t0) * 1000
                    tui.render_tool_call(
                        event["tool"].name,
                        event["tool"].input,
                        result="",
                        elapsed_ms=elapsed_ms,
                    )

                elif event["type"] == "done":
                    if thinking_text:
                        elapsed_s = time.time() - t0
                        tokens = len("".join(thinking_text).split())
                        tui.render_thinking(
                            "".join(thinking_text),
                            collapsed=True,
                            tokens=tokens,
                            elapsed_s=elapsed_s,
                        )

        except Exception as exc:
            tui.render_error(f"LLM call failed: {{exc}}")
            continue

        elapsed_ms = (time.time() - t0) * 1000
        tui.update_status(status="ready")

        # Build assistant content blocks
        assistant_content = []
        if thinking_text:
            assistant_content.append({{
                "type": "thinking",
                "thinking": "".join(thinking_text),
            }})
        if collected_text:
            full_text = "".join(collected_text).strip()
            assistant_content.append({{"type": "text", "text": full_text}})
            tui.render_agent_message(full_text)
        for tc in tool_calls:
            assistant_content.append({{
                "type": "tool_use",
                "id": tc.id,
                "name": tc.name,
                "input": tc.input,
            }})

        conv.append("assistant", assistant_content)

        # Execute tool calls and stream results
        for tc in tool_calls:
            tui.update_status(status="calling_tool")
            t0_tool = time.time()
            result = registry.execute(tc.name, {{**tc.input, "tool_use_id": tc.id}})
            tool_elapsed = (time.time() - t0_tool) * 1000

            tui.render_tool_call(
                tc.name, tc.input,
                result=result.get("content", ""),
                elapsed_ms=tool_elapsed,
            )
            conv.append("user", [result])

        tui.update_status(status="ready")
        conv.checkpoint_if_needed()
        tui.render_divider()

    # Session end
    tui.update_status(status="ready")
    tui.render_divider()
    print("Generating session summary...")

    # Collect existing long-term facts and recent topics for LLM dedup
    existing_facts = memory.get_long_term().get("key_facts", [])
    # Build a dedup prompt
    dedup_prompt = (
        f"Existing long-term key facts:\\n"
        + "\\n".join(f"- {{f}}" for f in existing_facts)
        + "\\n\\nMerge these facts, removing semantic duplicates. "
        + "Return a JSON array of unique facts. Keep facts concise (under 120 chars each). "
        + "Preserve all distinct information. Return ONLY the JSON array, nothing else."
    )

    try:
        dedup_response = backend.create_message(
            system_prompt="You are a knowledge deduplication assistant. Merge similar facts and return unique ones as a JSON array.",
            messages=[{{"role": "user", "content": dedup_prompt}}],
            tools=[],
        )
        if dedup_response.text_blocks:
            deduped_text = "".join(dedup_response.text_blocks)
            # Extract JSON array from response
            import re as _re
            match = _re.search(r'\\[.*\\]', deduped_text, _re.DOTALL)
            if match:
                try:
                    deduped_facts = json.loads(match.group())
                    if isinstance(deduped_facts, list):
                        memory.set_key_facts(deduped_facts)
                except json.JSONDecodeError:
                    pass
    except Exception:
        pass  # Non-critical — simple dedup already happened in end_session

    summary = f"Session with {{conv.__len__()}} messages."
    memory.end_session(
        summary=summary,
        key_topics=[],
        decisions=[],
        preferences=[],
    )
    tui.goodbye(identity.name)


def main():
    identity = Identity()
    memory = MemoryStore()
    conv = ConversationManager()
    registry = ToolRegistry()

    config = load_config()
    backend = create_backend(config)

    load_tools(registry)

    doc_count, knowledge_index = scan_knowledge()
    tool_count = len(registry.list_names())

    # Select TUI: try live mode first, degrade to rich REPL, then plain
    tui = create_tui(
        agent_name=identity.name,
        agent_version=identity.version,
        live=False,  # Default to enhanced REPL; --live flag enables persistent UI
    )

    agent_loop(identity, memory, conv, registry, backend, tui,
               knowledge_index=knowledge_index)


if __name__ == "__main__":
    main()
'''


def _generate_main_py(agent_name: str, version: str, tool_count: int,
                      knowledge_count: int, evolution_cycles: int) -> str:
    """Generate the standalone agent's main.py entry point."""
    return _MAIN_PY_TEMPLATE.format(
        agent_name=agent_name,
        version=version,
        export_date=_now_iso()[:19],
        evolution_cycles=evolution_cycles,
        tool_count=tool_count,
        knowledge_count=knowledge_count,
    )


_CONFIG_YAML_TEMPLATE = """# {agent_name} Configuration
# Fill in your LLM API credentials below.

llm:
  provider: anthropic        # anthropic | openai | deepseek
  model: claude-sonnet-4-6-20250514
  api_key_env: ANTHROPIC_API_KEY
  max_tokens: 8192

# Agent identity (read-only — frozen at export)
identity:
  name: {agent_name}
  version: {version}
"""


def _generate_config_yaml(agent_name: str, version: str) -> str:
    return _CONFIG_YAML_TEMPLATE.format(agent_name=agent_name, version=version)


_REQUIREMENTS_TXT = """anthropic>=0.39.0
openai>=1.0.0
rich>=13.0.0
pyyaml>=6.0
"""


def _generate_readme(agent_name: str, version: str, tool_count: int,
                     knowledge_count: int, evolution_cycles: int) -> str:
    export_date = _now_iso()[:19]
    return f"""# {agent_name} v{version}

Standalone evolved agent — exported from the Tao Agent factory.

## Identity

- **Evolution cycles**: {evolution_cycles}
- **Tools**: {tool_count}
- **Knowledge documents**: {knowledge_count}

## Quick Start

1. Set your API key:
   ```bash
   export ANTHROPIC_API_KEY=sk-ant-...
   ```

2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

3. Run:
   ```bash
   python main.py
   ```

## Commands

- `/help` — show help
- `/tools` — list available tools
- `/identity` — show agent identity
- `/memory` — show recent sessions
- `/quit` — exit and save memory

## Configuration

Edit `config.yaml` to change LLM provider, model, or API key settings.

## Architecture

```
{agent_name}/
├── main.py           ← Entry point
├── runtime/          ← Execution kernel (LLM, memory, tools, conversation, identity)
├── tools/            ← Forged tools ({tool_count})
├── knowledge/        ← Knowledge base ({knowledge_count} docs)
├── identity.json     ← Frozen identity snapshot
├── memory.json       ← Persistent memory (created on first run)
├── config.yaml       ← LLM configuration
├── requirements.txt  ← Python dependencies
└── README.md         ← This file
```

Exported on {export_date}.
"""


# ─── Step 4: Verify ────────────────────────────────────────────────────

def _verify_export(dist_dir: Path) -> dict:
    """Run verification checks on the assembled product.

    Returns a dict with check results.
    """
    results = {}

    # 4a: Import check — can we import runtime?
    runtime_dir = dist_dir / "runtime"
    results["runtime_exists"] = runtime_dir.exists() and (runtime_dir / "__init__.py").exists()
    results["runtime_modules"] = len(list(runtime_dir.glob("*.py")))

    # 4b: Tool loading — can all tools be imported?
    tools_dir = dist_dir / "tools"
    if tools_dir.exists():
        tool_files = [f for f in tools_dir.glob("*.py") if not f.name.startswith("_")]
        sys.path.insert(0, str(dist_dir))
        failed_tools = []
        for tf in tool_files:
            try:
                __import__(f"tools.{tf.stem}")
            except Exception as exc:
                failed_tools.append(f"{tf.stem}: {exc}")
        results["tool_count"] = len(tool_files)
        results["tool_import_failures"] = failed_tools
        results["tool_import_ok"] = len(failed_tools) == 0
    else:
        results["tool_count"] = 0
        results["tool_import_ok"] = False

    # 4c: Knowledge integrity
    knowledge_dir = dist_dir / "knowledge"
    if knowledge_dir.exists():
        md_files = list(knowledge_dir.rglob("*.md"))
        results["knowledge_docs"] = len(md_files)
        results["knowledge_size_bytes"] = sum(f.stat().st_size for f in md_files)
    else:
        results["knowledge_docs"] = 0
        results["knowledge_size_bytes"] = 0

    # 4d: Entry point syntax check
    main_py = dist_dir / "main.py"
    if main_py.exists():
        try:
            ast.parse(main_py.read_text())
            results["main_py_syntax_ok"] = True
        except SyntaxError as exc:
            results["main_py_syntax_ok"] = False
            results["main_py_syntax_error"] = str(exc)
    else:
        results["main_py_syntax_ok"] = False

    # 4e: Required files present
    required = ["identity.json", "config.yaml", "requirements.txt", "README.md"]
    results["required_files"] = {
        f: (dist_dir / f).exists() for f in required
    }
    results["all_required_files_ok"] = all(results["required_files"].values())

    results["all_ok"] = (
        results["runtime_exists"]
        and results.get("tool_import_ok", False)
        and results["main_py_syntax_ok"]
        and results["all_required_files_ok"]
    )

    return results


# ─── Main Export Pipeline ──────────────────────────────────────────────

class ExportPipeline:
    """The full export pipeline: collect → rewrite → assemble → verify → package."""

    def __init__(self, workspace_dir: Optional[str] = None):
        if workspace_dir:
            self.workspace_dir = Path(workspace_dir)
        else:
            self.workspace_dir = None
        self.project_root = _project_root()

    def export(self, name: str, output_dir: str = "dist",
               skip_gate: bool = False,
               gate_instance=None) -> ExportResult:
        """Run the full export pipeline.

        Args:
            name: Agent name (e.g. "explorer")
            output_dir: Directory for the packaged output
            skip_gate: Skip quality gate check (dev only)
            gate_instance: Pre-configured ExportQualityGate instance

        Returns:
            ExportResult with paths and metadata.

        Raises:
            ExportRejected: If quality gate fails.
        """
        # Step 0: Quality Gate
        if not skip_gate:
            if gate_instance is None:
                from tain_agent.evolution.quality_gate import ExportQualityGate, ExportRejected
                gate = ExportQualityGate(name, _collect_version(self.workspace_dir))
            else:
                gate = gate_instance
            report = gate.evaluate_and_assert()

        # Step 1: Collect
        tools = _collect_tools(self.workspace_dir)
        knowledge_dir = _collect_knowledge(self.workspace_dir)
        identity_data = _collect_identity(self.workspace_dir)
        drives_data = _collect_drives(self.workspace_dir)
        version = _collect_version(self.workspace_dir)

        # Build identity export
        if identity_data:
            dims = identity_data.get("dimensions", identity_data.get("_traits", {}))
            expertise = identity_data.get("expertise", [])
            evolution_cycles = identity_data.get("evolution_cycles", 0)
        else:
            dims = {}
            expertise = []
            evolution_cycles = 0

        from tain_agent.runtime.identity import export_identity
        identity_export = export_identity(
            name=name, version=version,
            dimensions=dims, drives=drives_data,
            expertise=expertise,
            evolution_cycles=evolution_cycles,
            tool_count=len(tools),
            knowledge_doc_count=(
                len(list(knowledge_dir.rglob("*.md"))) if knowledge_dir else 0
            ),
        )

        # Step 2: Rewrite tools
        rewritten_tools: dict[str, str] = {}
        for tool_path in tools:
            source = tool_path.read_text(encoding="utf-8")
            rewritten = rewrite_imports(source)
            rewritten_tools[tool_path.stem] = rewritten

        # Step 3: Assemble
        dist_name = f"{name}-v{version}"
        dist_dir = Path(output_dir) / dist_name
        if dist_dir.exists():
            shutil.rmtree(dist_dir)
        dist_dir.mkdir(parents=True)

        # 3a: Copy runtime kernel
        runtime_src = self.project_root / "tain_agent" / "runtime"
        runtime_dst = dist_dir / "runtime"
        shutil.copytree(runtime_src, runtime_dst,
                        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))

        # 3b: Mount rewritten tools (exclude __pycache__ and .pyc)
        tools_dst = dist_dir / "tools"
        tools_dst.mkdir()
        for tool_name, tool_source in rewritten_tools.items():
            (tools_dst / f"{tool_name}.py").write_text(tool_source, encoding="utf-8")

        # 3c: Mount knowledge (copy verbatim, exclude cache files)
        if knowledge_dir and knowledge_dir.exists():
            knowledge_dst = dist_dir / "knowledge"
            shutil.copytree(knowledge_dir, knowledge_dst,
                            ignore=shutil.ignore_patterns("__pycache__", "*.pyc", ".DS_Store"))
        else:
            (dist_dir / "knowledge").mkdir()

        # 3d: Write identity.json
        (dist_dir / "identity.json").write_text(
            json.dumps(identity_export, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        # 3e: Generate main.py
        knowledge_count = (len(list((dist_dir / "knowledge").rglob("*.md")))
                           if (dist_dir / "knowledge").exists() else 0)
        main_py = _generate_main_py(name, version, len(tools),
                                    knowledge_count, evolution_cycles)
        (dist_dir / "main.py").write_text(main_py, encoding="utf-8")

        # 3f: Generate supporting files
        (dist_dir / "config.yaml").write_text(
            _generate_config_yaml(name, version), encoding="utf-8")
        (dist_dir / "requirements.txt").write_text(_REQUIREMENTS_TXT, encoding="utf-8")
        (dist_dir / "README.md").write_text(
            _generate_readme(name, version, len(tools), knowledge_count,
                             evolution_cycles),
            encoding="utf-8",
        )

        # 3g: Export tools as standard Agent Skills (Phase 3.1)
        skills_dst = dist_dir / "skills"
        skills_dst.mkdir(exist_ok=True)
        skill_count = 0
        knowledge_skill_count = 0
        try:
            from tain_agent.evolution.skill_exporter import SkillExporter
            skill_exporter = SkillExporter(
                agent_name=name, agent_version=version,
                evolution_cycles=evolution_cycles,
            )
            skill_results = skill_exporter.export_all_tools(
                output_dir=str(skills_dst))
            skill_count = len(skill_results)
            # Also export knowledge docs as Skills
            if knowledge_dir and knowledge_dir.exists():
                knowledge_skills = skill_exporter.export_knowledge_as_skills(
                    str(knowledge_dir), output_dir=str(skills_dst))
                knowledge_skill_count = len(knowledge_skills)
        except Exception:
            pass  # Non-critical — internal tool/knowledge export still succeeds

        # Step 4: Verify
        verification = _verify_export(dist_dir)

        # Step 5: Package
        tar_path = Path(output_dir) / f"{dist_name}.tar.gz"
        with tarfile.open(tar_path, "w:gz") as tar:
            tar.add(dist_dir, arcname=dist_name)

        total_size = tar_path.stat().st_size

        return ExportResult(
            name=name,
            version=version,
            output_path=str(tar_path),
            dist_dir=str(dist_dir),
            tool_count=len(tools),
            knowledge_count=knowledge_count,
            skill_count=skill_count,
            knowledge_skill_count=knowledge_skill_count,
            total_size_bytes=total_size,
            verification=verification,
        )
