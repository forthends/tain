"""
TUI — rich-based terminal interface for standalone agents.

Provides Claude Code-aligned UX: streaming output, collapsible
thinking blocks, tool call visualization, status bar, shortcut bar.

Three tiers (auto-selected by create_tui):
  LiveTUI  — rich.Live persistent layout (status bar + body + shortcut bar)
  RichTUI  — rich formatting without Live (enhanced REPL)
  PlainTUI — pure text fallback when rich is not installed

Zero framework dependencies — uses only stdlib + optional rich.
"""

import os
import re
import sys
from contextlib import contextmanager
from typing import Optional


# ─── Plain-text fallback ──────────────────────────────────────────────

class PlainTUI:
    """Minimal plain-text TUI — always available as fallback."""

    def __init__(self, agent_name: str = "Agent", agent_version: str = "0.1.0"):
        self.agent_name = agent_name
        self.agent_version = agent_version
        self.tool_count = 0
        self.doc_count = 0
        self.status = "ready"
        self._thinking_expanded = False

    def startup(self, intro_text: str):
        print(intro_text)

    def status_line(self):
        pass  # no-op in plain mode

    def update_status(self, **kwargs):
        for k, v in kwargs.items():
            setattr(self, k, v)

    def render_thinking(self, text: str, collapsed: bool = True) -> str:
        if collapsed:
            lines = text.strip().split("\n")
            preview = lines[0][:80] if lines else ""
            return f"  [thinking] {preview}..."
        else:
            return f"  [thinking]\n    " + text.strip().replace("\n", "\n    ")

    def render_tool_call(self, name: str, input_data: dict, result: str = "",
                         elapsed_ms: float = 0) -> str:
        parts = [f"  [tool] {name} ({elapsed_ms:.0f}ms)"]
        if result:
            preview = result[:200]
            parts.append(f"    -> {preview}")
        return "\n".join(parts)

    def render_user_message(self, text: str) -> str:
        return f"> {text}"

    def render_agent_message(self, text: str) -> str:
        return f"\n{self.agent_name}: {text}\n"

    def render_stream(self, text: str):
        sys.stdout.write(text)
        sys.stdout.flush()

    def render_prompt(self) -> str:
        return input("> ")

    def render_divider(self):
        print("─" * 60)

    def render_error(self, msg: str):
        print(f"\n[error] {msg}")

    def goodbye(self, name: str):
        print(f"\nMemory saved. Goodbye from {name}.")


# ─── Rich TUI (enhanced REPL) ────────────────────────────────────────────

try:
    from rich.console import Console
    from rich.layout import Layout
    from rich.live import Live
    from rich.panel import Panel
    from rich.text import Text
    from rich.markdown import Markdown
    from rich import box
    _RICH_AVAILABLE = True
except ImportError:
    _RICH_AVAILABLE = False


if _RICH_AVAILABLE:
    class RichTUI:
        """Rich-powered TUI — enhanced REPL with rich formatting.

        Uses console.print for sequential output with rich styling.
        Does NOT use Live — for persistent layout see LiveTUI below.
        """

        def __init__(self, agent_name: str = "Agent", agent_version: str = "0.1.0"):
            self.agent_name = agent_name
            self.agent_version = agent_version
            self.tool_count = 0
            self.doc_count = 0
            self.status = "ready"
            self._thinking_expanded = False
            self.console = Console()

        def startup(self, intro_text: str):
            """Print the boot sequence with a box."""
            panel = Panel(
                intro_text,
                title=f"{self.agent_name} v{self.agent_version}",
                border_style="cyan",
                box=box.ROUNDED,
            )
            self.console.print(panel)

        def update_status(self, **kwargs):
            for k, v in kwargs.items():
                setattr(self, k, v)

        def render_thinking(self, text: str, collapsed: bool = True,
                            tokens: int = 0, elapsed_s: float = 0):
            """Render a thinking block (collapsible via /think command)."""
            if self._thinking_expanded:
                panel = Panel(
                    text.strip(),
                    title="thinking",
                    border_style="dim",
                    box=box.MINIMAL,
                    padding=(0, 2),
                )
                self.console.print(panel)
            else:
                preview = text.strip().split("\n")[0][:100]
                header = Text()
                header.append("  [thinking] ", style="dim")
                header.append(preview, style="italic dim")
                if elapsed_s:
                    header.append(f" ({elapsed_s:.1f}s)", style="dim")
                if tokens:
                    header.append(f", {tokens} tokens", style="dim")
                header.append("  [/think to expand]", style="dim")
                self.console.print(header)

        def render_tool_call(self, name: str, input_data: dict,
                             result: str = "", elapsed_ms: float = 0):
            """Render a tool call as a foldable block."""
            input_str = str(input_data)
            if len(input_str) > 120:
                input_str = input_str[:120] + "..."

            lines = [f"Input: {input_str}"]
            if result:
                result_preview = result[:300]
                if len(result) > 300:
                    result_preview += "..."
                lines.append(f"Result: {result_preview}")

            title = Text()
            title.append("tool ", style="dim")
            title.append(name, style="bold")
            if elapsed_ms:
                title.append(f" ({elapsed_ms:.0f}ms)", style="dim")

            self.console.print(Panel(
                "\n".join(lines),
                title=title,
                border_style="blue",
                box=box.MINIMAL,
                padding=(0, 2),
            ))

        def render_user_message(self, text: str):
            msg = Text("> ", style="bold green")
            msg.append(text)
            self.console.print(msg)

        def render_agent_message(self, text: str):
            self.console.print(Markdown(text))

        def render_stream(self, text: str):
            self.console.print(text, end="", highlight=False)

        def render_prompt(self) -> str:
            prompt = Text("> ", style="bold green")
            self.console.print(prompt, end="")
            try:
                return input()
            except (EOFError, KeyboardInterrupt):
                return "/quit"

        def render_divider(self):
            self.console.print("─" * self.console.width, style="dim")

        def render_error(self, msg: str):
            self.console.print(f"\n[error] {msg}", style="bold red")

        def goodbye(self, name: str):
            self.console.print(f"\nMemory saved. Goodbye from {name}.", style="italic")


    class LiveTUI:
        """Full persistent TUI using rich.Live with fixed layout.

        Three regions:
          header  — status bar (agent name, version, tool count, status)
          body    — scrolling conversation (thinking, tool calls, messages)
          footer  — shortcut bar

        Live rendering is paused for user input and resumed afterwards.
        """

        def __init__(self, agent_name: str = "Agent", agent_version: str = "0.1.0"):
            self.agent_name = agent_name
            self.agent_version = agent_version
            self.tool_count = 0
            self.doc_count = 0
            self.status = "ready"
            self._thinking_expanded = False
            self._body_lines: list = []

            self.console = Console()
            self._live: Optional[Live] = None

            self._build_layout()

        def _build_layout(self):
            self.layout = Layout()
            self.layout.split_column(
                Layout(name="header", size=3),
                Layout(name="body"),
                Layout(name="footer", size=1),
            )
            self.layout["header"].update(self._render_status_bar())
            self.layout["footer"].update(self._render_shortcut_bar())
            self.layout["body"].update(Panel("", border_style="dim", box=box.MINIMAL))

        def _render_status_bar(self) -> Panel:
            tools_str = f"{self.tool_count} tools" if self.tool_count else ""
            docs_str = f"{self.doc_count} docs" if self.doc_count else ""
            status_icons = {
                "ready": "○", "thinking": "◌", "calling_tool": "⚙",
                "waiting": "▸", "error": "✗",
            }
            icon = status_icons.get(self.status, "○")
            text = Text()
            text.append(f" {self.agent_name} v{self.agent_version} ", style="bold")
            if tools_str:
                text.append(f"| {tools_str} ", style="dim")
            if docs_str:
                text.append(f"| {docs_str} ", style="dim")
            text.append(f"| {icon} {self.status} ", style="dim")
            return Panel(text, box=box.MINIMAL, height=1)

        def _render_shortcut_bar(self) -> Panel:
            shortcuts = [
                ("/help", "help"), ("/tools", "tools"),
                ("/knowledge", "search"), ("/think", "toggle thinking"),
                ("/clear", "clear"), ("/quit", "exit"),
            ]
            text = Text()
            for i, (key, label) in enumerate(shortcuts):
                if i > 0:
                    text.append("  ")
                text.append(key, style="bold dim")
                text.append(f" {label}", style="dim")
            return Panel(text, box=box.MINIMAL, height=1)

        # ── Context manager for Live ───────────────────────────────────

        def __enter__(self):
            self._live = Live(
                self.layout,
                refresh_per_second=4,
                screen=True,
                transient=False,
            )
            self._live.__enter__()
            return self

        def __exit__(self, *args):
            if self._live:
                self._live.__exit__(*args)
                self._live = None
            return False

        # ── Status updates ─────────────────────────────────────────────

        def update_status(self, **kwargs):
            for k, v in kwargs.items():
                setattr(self, k, v)
            self.layout["header"].update(self._render_status_bar())
            self.layout["footer"].update(self._render_shortcut_bar())

        def _refresh_body(self):
            """Update the body panel from accumulated lines."""
            body_text = "\n".join(self._body_lines[-50:])  # keep last 50 lines
            if not body_text.strip():
                body_text = " "
            self.layout["body"].update(
                Panel(body_text, border_style="dim", box=box.MINIMAL, padding=(0, 1))
            )

        # ── Rendering methods ──────────────────────────────────────────

        def startup(self, intro_text: str):
            """Print the boot sequence, then start Live."""
            # Print boot box before Live takes over the screen
            panel = Panel(
                intro_text,
                title=f"{self.agent_name} v{self.agent_version}",
                border_style="cyan",
                box=box.ROUNDED,
            )
            self.console.print(panel)

        def render_thinking(self, text: str, collapsed: bool = True,
                            tokens: int = 0, elapsed_s: float = 0):
            """Append a thinking block to the body."""
            if collapsed and not self._thinking_expanded:
                preview = text.strip().split("\n")[0][:100]
                line = f"  [thinking] {preview}"
                if elapsed_s:
                    line += f" ({elapsed_s:.1f}s)"
                if tokens:
                    line += f", {tokens} tokens"
                line += "  [/think to expand]"
                self._body_lines.append(line)
            else:
                self._body_lines.append("  ┌─ thinking ─".ljust(60, "─"))
                for line in text.strip().split("\n"):
                    self._body_lines.append(f"  │ {line}")
                self._body_lines.append("  └" + "─" * 59)
            self._refresh_body()

        def render_tool_call(self, name: str, input_data: dict,
                             result: str = "", elapsed_ms: float = 0):
            """Append a tool call visualization to the body."""
            input_str = str(input_data)
            if len(input_str) > 100:
                input_str = input_str[:100] + "..."

            self._body_lines.append(f"  ┌─ tool: {name} ({elapsed_ms:.0f}ms) ─".ljust(60, "─"))
            self._body_lines.append(f"  │ Input: {input_str}")
            if result:
                result_preview = result[:300]
                if len(result) > 300:
                    result_preview += "..."
                for line in result_preview.split("\n")[:8]:
                    self._body_lines.append(f"  │ {line[:76]}")
            self._body_lines.append("  └" + "─" * 59)
            self._refresh_body()

        def render_user_message(self, text: str):
            self._body_lines.append(f"> {text}")
            self._refresh_body()

        def render_agent_message(self, text: str):
            self._body_lines.append("")
            for line in text.strip().split("\n"):
                self._body_lines.append(f"  {line}")
            self._body_lines.append("")
            self._refresh_body()

        def render_stream(self, text: str):
            """Accumulate streaming text — caller should use render_agent_message for complete response."""
            if self._body_lines and not self._body_lines[-1].startswith("  [tool"):
                # Append to last line
                self._body_lines[-1] += text
            else:
                self._body_lines.append(f"  {text}")
            self._refresh_body()

        def render_prompt(self) -> str:
            """Pause Live, get user input, resume Live."""
            if self._live:
                self._live.stop()
            try:
                sys.stdout.write("\r> ")
                sys.stdout.flush()
                return input()
            except (EOFError, KeyboardInterrupt):
                return "/quit"
            finally:
                if self._live:
                    self._live.start()

        def render_divider(self):
            self._body_lines.append("─" * 60)
            self._refresh_body()

        def render_error(self, msg: str):
            self._body_lines.append(f"[error] {msg}")
            self._refresh_body()

        def goodbye(self, name: str):
            self._body_lines.append(f"\nMemory saved. Goodbye from {name}.")
            self._refresh_body()


# ─── TUI Factory ───────────────────────────────────────────────────────

def create_tui(agent_name: str = "Agent", agent_version: str = "0.1.0",
               force_plain: bool = False, live: bool = False):
    """Create the appropriate TUI for the current environment.

    Selection logic:
      - PlainTUI if rich unavailable, not a TTY, or force_plain=True
      - LiveTUI if live=True and rich available (persistent layout)
      - RichTUI otherwise (enhanced REPL)

    Returns a TUI instance.
    """
    if not _RICH_AVAILABLE or not sys.stdout.isatty() or force_plain:
        return PlainTUI(agent_name, agent_version)
    if live and _RICH_AVAILABLE:
        return LiveTUI(agent_name, agent_version)
    return RichTUI(agent_name, agent_version)


# ─── Helpers for the main agent loop ───────────────────────────────────

HELP_TEXT = """
Commands:
  /help, /?          Show this help
  /tools, /t [query] List or search tools
  /knowledge, /k <q> Search knowledge base
  /identity, /id     Show agent personality and drives
  /memory, /mem      Show recent session summaries
  /think             Toggle thinking block visibility
  /clear             Clear screen
  /save              Manually save memory.json
  /quit, /exit, /q   Exit and save memory
"""


def dispatch_slash_command(cmd: str, identity, memory, registry, tui,
                           knowledge_dir: str = None) -> bool:
    """Handle a slash command. Returns True if the agent should quit."""
    parts = cmd.split(maxsplit=1)
    cmd_name = parts[0].lower()
    arg = parts[1] if len(parts) > 1 else ""

    if cmd_name in ("/quit", "/exit", "/q"):
        return True

    elif cmd_name in ("/help", "/?"):
        if hasattr(tui, "console"):
            tui.console.print(HELP_TEXT)
        else:
            print(HELP_TEXT)

    elif cmd_name in ("/tools", "/t"):
        names = registry.list_names()
        if arg:
            names = [n for n in names if arg.lower() in n.lower()]
        if names:
            print(f"{len(names)} tools: {', '.join(names)}")
        else:
            print("No tools registered.")

    elif cmd_name in ("/knowledge", "/k"):
        if not arg:
            print("Usage: /knowledge <query>")
            return False
        if knowledge_dir:
            from pathlib import Path
            kd = Path(knowledge_dir)
            if kd.exists():
                matches = []
                for md in kd.rglob("*.md"):
                    if arg.lower() in md.name.lower():
                        matches.append(md.name)
                    elif arg.lower() in md.read_text(encoding="utf-8")[:500].lower():
                        matches.append(md.name)
                if matches:
                    print(f"Found {len(matches)} docs: {', '.join(matches[:10])}")
                else:
                    print("No matching documents found.")
            else:
                print("Knowledge directory not found.")
        else:
            print("No knowledge directory configured.")

    elif cmd_name in ("/identity", "/id"):
        print(f"{identity.name} v{identity.version}")
        print(f"Evolution cycles: {identity.evolution_cycles}")
        print(f"Traits: {identity.trait_count()}")
        print(f"Dominant drive: {identity.dominant_drive()}")
        drives = identity.all_drives()
        for name, d in drives.items():
            intensity = d.get("intensity", 0) if isinstance(d, dict) else d
            bar = "█" * int(intensity * 10) + "░" * (10 - int(intensity * 10))
            print(f"  {name}: {bar} {intensity:.2f}")

    elif cmd_name in ("/memory", "/mem"):
        sessions = memory.recent_sessions(5)
        if not sessions:
            print("No previous sessions.")
        for s in sessions:
            started = s.get("started", "")[:10]
            summary = s.get("summary", "")[:120]
            topics = s.get("key_topics", [])
            print(f"  {started}: {summary}")
            if topics:
                print(f"    Topics: {', '.join(topics[:5])}")

    elif cmd_name == "/think":
        if hasattr(tui, "_thinking_expanded"):
            tui._thinking_expanded = not tui._thinking_expanded
            state = "expanded" if tui._thinking_expanded else "collapsed"
            print(f"Thinking blocks: {state}")

    elif cmd_name == "/clear":
        if hasattr(tui, "_live") and tui._live:
            tui._body_lines = []
            tui._refresh_body()
        else:
            os.system("clear" if os.name != "nt" else "cls")

    elif cmd_name == "/save":
        memory.save()
        print("Memory saved.")

    return False
