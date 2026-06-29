#!/usr/bin/env python3
"""
Tain Agent Framework — 道生一，一生二，二生三，三生万物

Entry point for the Tain Agent Framework. Create, manage, and run
self-evolving AI agents.

Usage:
    python main.py --agent <name>              Start a specific agent (creates if new)
    python main.py --agent <name> --dialogue   Start agent in dialogue mode
    python main.py --list-agents               List all agents
    python main.py --create-agent              Interactive agent creation wizard
    python main.py --agent <name> --state      View agent state
    python main.py --agent <name> --log        View agent decision log
    python main.py --agent <name> --export     Export agent as standalone package
    python main.py --daemon --agent <name>     Run agent as daemon with auto-restart
    python main.py --daemon --stop             Stop the running daemon
    python main.py --daemon --status           Check daemon status
"""

import argparse
import logging
import os
import re
import subprocess
import sys
from pathlib import Path

# Configure logging early so all modules benefit.
# StreamHandler → stdout so the guardian captures agent output for the Live tab.
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    datefmt="%H:%M:%S",
    stream=sys.stdout,
)

# Ensure the project root is in sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent))

from tain_agent.core.agent_factory import AgentFactory
from tain_agent.kernel import AgentKernel, AgentContext, STANDARD_FACTORIES
from tain_agent.kernel import EVOLVE_SYSTEM_PROMPT
from tain_agent.core.llm import LLMBackend
from tain_agent.core.conversation import ConversationManager
from tain_agent.core.drives import DriveSystem
from tain_agent import __version__

# ─── Constants ──────────────────────────────────────────────────────────

AGENT_NAME_HELP = (
    "Agent name (letters, digits, hyphens, underscores; "
    "1-32 chars, must start with a letter). Example: poet, Philosopher, alpha01"
)


# ─── Agent Creation Wizard ──────────────────────────────────────────────

def run_creation_wizard(factory: AgentFactory, suggested_name: str = "") -> str:
    """Interactive agent creation flow. Returns the created agent name."""
    print()
    print("=" * 56)
    print("  Create New Agent — 创建新Agent")
    print("=" * 56)
    print()

    # ── Step 1: Agent name ──────────────────────────────────────────
    while True:
        if suggested_name:
            prompt = f"Agent name [{suggested_name}]: "
        else:
            prompt = "Agent name: "

        name = input(prompt).strip()
        if not name and suggested_name:
            name = suggested_name

        if not name:
            print("  Name cannot be empty.")
            continue
        if not re.match(r"^[a-zA-Z][a-zA-Z0-9_-]{0,31}$", name):
            print("  Invalid name. Must be 1-32 chars, letters/digits/hyphens/underscores, start with a letter.")
            continue
        if factory.exists(name):
            print(f"  Agent '{name}' already exists. Choose a different name.")
            continue
        break

    # ── Step 2: Evolution mode ──────────────────────────────────────
    print()
    print("  Select evolution mode:")
    print("    1. 混沌模式 (Chaos) — 从空白人格开始，Agent自我觉醒，自我定义")
    print("    2. 指定人格模式 (Specified) — 预设角色与人格特质")
    print()

    while True:
        mode_choice = input("  Choice [1/2]: ").strip()
        if mode_choice in ("1", "2"):
            break
        print("  Please enter 1 or 2.")

    mode = "chaos" if mode_choice == "1" else "specified"
    role = ""
    role_description = ""

    # ── Step 3: Role details (specified mode only) ──────────────────
    if mode == "specified":
        print()
        print("  " + "-" * 48)
        print("  Specify the agent's role and personality.")
        print("  Example: role=浪漫主义诗人, description=随性、浪漫的现代诗人...")
        print("  " + "-" * 48)
        print()

        while True:
            role = input("  Role name (e.g. 浪漫主义诗人): ").strip()
            if role:
                break
            print("  Role name cannot be empty.")

        print()
        while True:
            role_description = input("  Role description: ").strip()
            if role_description:
                break
            print("  Role description cannot be empty.")

    # ── Step 4: Create ──────────────────────────────────────────────
    from tain_agent import __version__ as fw_version

    print()
    print(f"  Creating agent '{name}' ({mode} mode)...")
    result = factory.create(
        name=name,
        mode=mode,
        role=role,
        role_description=role_description,
        framework_version=fw_version,
    )

    if "error" in result:
        print(f"\n  Error: {result['error']}")
        sys.exit(1)

    print(f"  Agent '{name}' created successfully.")
    print(f"    Mode: {mode}")
    if role:
        print(f"    Role: {role}")
        print(f"    Description: {role_description}")
    print(f"    Workspace: agent_workspace/{name}/")
    print()
    return name


# ─── List Agents ────────────────────────────────────────────────────────

def list_agents(factory: AgentFactory) -> None:
    """Display all registered agents."""
    agents = factory.list_agents()
    if not agents:
        print("(no agents created yet — use --create-agent or specify a new name)")
        return

    print()
    print(f"{'NAME':<16} {'MODE':<12} {'ROLE':<20} {'VERSION':<10} {'STATUS':<10} {'LAST ACTIVE'}")
    print("-" * 90)
    for name, info in sorted(agents.items()):
        role = info.get("role") or "—"
        ver = info.get("framework_version", "—")
        status = info.get("status", "stopped")
        last = (info.get("last_active_at") or "—")[:16]
        print(f"{name:<16} {info.get('evolution_mode', 'chaos'):<12} "
              f"{role:<20} {ver:<10} {status:<10} {last}")
    print()


# ─── Main ───────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Tain Agent Framework — 道生一，一生二，二生三，三生万物",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    # Agent selection
    parser.add_argument("--agent", "-a", type=str, action="append", default=None,
                        help=f"Agent name(s) to start (creates if new). Repeat for multiple agents. {AGENT_NAME_HELP}")
    parser.add_argument("--list-agents", action="store_true",
                        help="List all agents")
    parser.add_argument("--create-agent", action="store_true",
                        help="Interactive agent creation wizard")

    # Configuration
    parser.add_argument("--config", default="config.yaml", help="Path to config file")

    # Mode
    parser.add_argument("--pral", action="store_true",
                        help="Run with full PRAL cognitive cycle (default)")
    parser.add_argument("--no-pral", action="store_true",
                        help="Run without PRAL cognitive cycle (daemon passthrough)")
    parser.add_argument("--dialogue", "-d", action="store_true",
                        help="Start in interactive human-AI dialogue mode (REPL)")
    parser.add_argument("--cycles", type=int, default=0,
                        help="Max cycles override (0 = use config defaults)")

    # Inspection
    parser.add_argument("--state", action="store_true", help="Print current agent state")
    parser.add_argument("--log", action="store_true", help="View decision log")
    parser.add_argument("--phase", type=str, help="Filter log by phase")

    # Export
    parser.add_argument("--export", action="store_true",
                        help="Export agent as standalone package")
    parser.add_argument("--output", type=str, default="dist",
                        help="Output directory for export")
    parser.add_argument("--skip-gate", action="store_true",
                        help="Skip quality gate during export (dev only)")
    parser.add_argument("--eval", action="store_true",
                        help="Run quality gate evaluation and print report")
    parser.add_argument("--import", type=str, dest="import_path", default="",
                        help="Import an exported agent back into the factory")

    # Daemon
    parser.add_argument("--daemon", nargs="?", const="start",
                        choices=["start", "stop", "status"],
                        help="Run agent as a daemon with auto-restart")

    # Web UI
    parser.add_argument("--webui", action="store_true",
                        help="Start the Web UI management interface")
    parser.add_argument("--port", type=int, default=8000,
                        help="Port for Web UI (default: 8000)")

    # MCP / IDE embedding
    parser.add_argument("--mcp-serve", action="store_true", help="Start agent as MCP Server for IDE embedding")
    parser.add_argument("--export-bundle", action="store_true", help="Export agent as standalone Skill Bundle")
    parser.add_argument("--list-production-ready", action="store_true", help="List all production-ready agents")

    # ---- Subcommands ----
    subparsers = parser.add_subparsers(dest="command")

    # ---- Package subcommand ----
    pkg_parser = subparsers.add_parser("package", help="Manage Agent packages")
    pkg_sub = pkg_parser.add_subparsers(dest="package_action")

    pkg_create = pkg_sub.add_parser("create", help="Create a new package")
    pkg_create.add_argument("--name", required=True, help="Package name")
    pkg_create.add_argument("--kind", default="agent", choices=["agent", "toolset", "skill"])
    pkg_create.add_argument("--version", default="0.0.0")
    pkg_create.add_argument("--mode", default="chaos", choices=["chaos", "specified"])

    pkg_sub.add_parser("list", help="List packages")

    pkg_validate = pkg_sub.add_parser("validate", help="Validate a package")
    pkg_validate.add_argument("--name", required=True)

    pkg_export = pkg_sub.add_parser("export", help="Export a package")
    pkg_export.add_argument("--name", required=True)
    pkg_export.add_argument("--output", default="dist")
    pkg_export.add_argument("--format", choices=["dir", "tar.gz"], default="dir",
                            help="Export format (default: dir)")

    pkg_import = pkg_sub.add_parser("import", help="Import a package")
    pkg_import.add_argument("--source", required=True, dest="import_source")

    args = parser.parse_args()

    # ── Package subcommand dispatch ──────────────────────────────────
    if hasattr(args, "package_action") and args.package_action:
        from pathlib import Path as _Path
        from tain_agent.package.cli import (
            cmd_package_create, cmd_package_validate, cmd_package_list,
            cmd_package_export, cmd_package_import,
        )
        import json as _json
        if args.package_action == "create":
            result = cmd_package_create(name=args.name, kind=args.kind, version=args.version, evolution_mode=args.mode)
        elif args.package_action == "list":
            result = cmd_package_list()
        elif args.package_action == "validate":
            result = cmd_package_validate(name=args.name)
        elif args.package_action == "export":
            result = cmd_package_export(name=args.name, output=_Path(args.output),
                                         format=args.format)
        elif args.package_action == "import":
            result = cmd_package_import(source=_Path(args.import_source))
        else:
            result = {"ok": False, "error": f"Unknown action: {args.package_action}"}
        print(_json.dumps(result, indent=2, ensure_ascii=False))
        sys.exit(0 if result.get("ok") else 1)

    # ── Web UI ────────────────────────────────────────────────────────
    if args.webui:
        from webui.app import create_app
        import uvicorn
        app = create_app()
        print(f"\n  Tain Agent Framework Web UI v{__version__}")
        print(f"  → http://127.0.0.1:{args.port}\n")
        uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="info",
                    timeout_graceful_shutdown=3)
        return

    # ── Factory (for listing, creation) ─────────────────────────────
    factory = AgentFactory()

    # ── List agents ─────────────────────────────────────────────────
    if args.list_agents:
        list_agents(factory)
        return

    # ── Create agent wizard ─────────────────────────────────────────
    if args.create_agent:
        suggested = (args.agent[0] if args.agent else "")
        run_creation_wizard(factory, suggested_name=suggested)
        return

    # ── Determine agent name(s) ──────────────────────────────────────
    agent_names = args.agent  # list of str or None

    # ── Daemon commands ─────────────────────────────────────────────
    if args.daemon:
        supervisor_script = Path(__file__).resolve().parent / "supervise_agent.py"

        try:
            if args.daemon == "stop":
                if agent_names:
                    for name in agent_names:
                        subprocess.run([sys.executable, str(supervisor_script),
                                        "--agent-name", name, "--stop"])
                else:
                    subprocess.run([sys.executable, str(supervisor_script), "--stop-all"])

            elif args.daemon == "status":
                if agent_names:
                    for name in agent_names:
                        subprocess.run([sys.executable, str(supervisor_script),
                                        "--agent-name", name, "--status"])
                else:
                    subprocess.run([sys.executable, str(supervisor_script), "--status-all"])

            else:  # start
                if not agent_names:
                    print("Error: --daemon start requires at least one --agent <name>")
                    sys.exit(1)
                passthrough = []
                if args.dialogue:
                    passthrough.append("--dialogue")
                if args.no_pral:
                    passthrough.append("--no-pral")
                if args.cycles:
                    passthrough.extend(["--cycles", str(args.cycles)])
                for name in agent_names:
                    subprocess.run([sys.executable, str(supervisor_script),
                                    "--agent-name", name, "--daemon", "--"] + passthrough)
        except KeyboardInterrupt:
            print()
        return

    # ── Non-daemon modes: require exactly one agent ──────────────────
    if not agent_names:
        import yaml
        config_path = args.config
        cfg = {}
        if Path(config_path).exists():
            with open(config_path, "r", encoding="utf-8") as f:
                cfg = yaml.safe_load(f) or {}
        agent_name = cfg.get("agent", {}).get("default_agent", "default")
    elif len(agent_names) > 1:
        print("Error: multiple --agent only supported with --daemon start")
        sys.exit(1)
    else:
        agent_name = agent_names[0]

    # ── Agent doesn't exist → creation flow ─────────────────────────
    if not factory.exists(agent_name):
        print(f"\n  Agent '{agent_name}' not found.")
        if not sys.stdin.isatty():
            print("  Non-interactive mode — cannot create agent. Use --create-agent first.")
            sys.exit(1)
        response = input(f"  Create new agent '{agent_name}'? [Y/n]: ").strip().lower()
        if response and response != "y":
            print("  Aborted.")
            return
        agent_name = run_creation_wizard(factory, suggested_name=agent_name)

    # ── Compatibility check ─────────────────────────────────────────
    from tain_agent import __version__ as fw_version
    compatible, msg = factory.check_compatibility(agent_name, fw_version)
    if not compatible:
        print(f"\n  Warning: {msg}")
        print("  The agent may need migration. Proceeding anyway...\n")

    # ── Wake the agent ──────────────────────────────────────────────
    import yaml
    from pathlib import Path
    config_path = args.config
    cfg = {}
    if Path(config_path).exists():
        with open(config_path, "r", encoding="utf-8") as f:
            cfg = yaml.safe_load(f) or {}

    evolution_mode = cfg.get("agent", {}).get("evolution_mode", "specified")
    workspace = Path("agent_workspace") / agent_name

    ctx = AgentContext(
        agent_name=agent_name,
        agent_id=f"{agent_name}-{workspace.name}",
        evolution_mode=evolution_mode,
        workspace_path=workspace,
        config=cfg,
        kernel_version=__version__,
    )
    kernel = AgentKernel(ctx)
    kernel.load_plugins(STANDARD_FACTORIES)

    # Create LLM backend, conversation, drives (same pattern as old compat.py)
    from tain_agent.core.llm import create_backend
    backend = create_backend(cfg)
    conversation = ConversationManager(
        checkpoint_dir=str(workspace),
        auto_checkpoint_interval=10,
        token_limit=cfg.get("conversation", {}).get("token_limit", 80000),
        model_context_window=cfg.get("conversation", {}).get("model_context_window", 131072),
    )
    drives = DriveSystem()

    system_prompt = EVOLVE_SYSTEM_PROMPT.format(
        agent_name=agent_name,
        role=cfg.get("identity", {}).get("role", ""),
        role_description=cfg.get("identity", {}).get("role_description", ""),
    )

    class _DecisionLogShim:
        """Minimal shim for decision_log compatibility."""
        def __init__(self, entries=None):
            self._entries = entries or []
        def read_all(self):
            return list(self._entries)
        def filter_by_phase(self, phase):
            return [e for e in self._entries if e.get("phase") == phase]

    class _AgentStateAdapter:
        """Minimal adapter so main.py commands work with AgentKernel."""
        def __init__(self, kernel, agent_name, framework_version,
                     backend, config, conversation, phase="explore"):
            self.kernel = kernel
            self.agent_name = agent_name
            self.version = framework_version
            self.phase = phase
            self.backend = backend
            self.config = config
            self.conversation = conversation
            self.decision_log = _DecisionLogShim([])
            # Plugin accessors for dialogue/chat compatibility
            self.tools = kernel.lifecycle.get("tool")
            self.memory = kernel.lifecycle.get("memory")
            identity = kernel.lifecycle.get("identity")
            self.personality = identity.personality if identity else None
            self.forge = kernel.lifecycle.get("tool")  # ToolPlugin has forge methods
            knowledge = kernel.lifecycle.get("knowledge")
            self.goals = knowledge.goals if knowledge else None
            self.capability = None  # computed on-demand by dialogue.py

        def print_state(self):
            print(f"\n  Agent: {self.agent_name}")
            print(f"  Version: {self.version}")
            print(f"  Phase: {self.phase}")
            print(f"  Cycle: {self.kernel.pral.cycle_count}")
            print()
            for name, health in self.kernel.lifecycle.all_health_checks().items():
                status = getattr(health, 'status', str(health))
                print(f"  [{name}] {status}")
            print()

        def stop(self):
            self.kernel.shutdown()

        def run(self, autonomous=False):
            return self.kernel.run(backend, conversation, drives, system_prompt)

        def _execute_tool_calls(self, tool_calls):
            results = []
            for tc in tool_calls:
                result = self.kernel.dispatch.call("tool.call", tc.name, **tc.input)
                content = str(result) if result is not None else f"Tool '{tc.name}' returned no result"
                results.append({"tool_use_id": tc.id, "content": content})
            return results

    agent = _AgentStateAdapter(
        kernel, agent_name, __version__,
        backend, cfg, conversation,
    )

    if args.state:
        agent.print_state()
        return

    if args.log:
        if args.phase:
            entries = agent.decision_log.filter_by_phase(args.phase)
        else:
            entries = agent.decision_log.read_all()
        if not entries:
            print("(empty — no decisions recorded yet)")
        for e in entries:
            print(f"[{e.get('id', '????')}] {e.get('timestamp', '?')}")
            print(f"  阶段: {e.get('phase', '?')} | 类型: {e.get('decision_type', '?')}")
            print(f"  选择: {e.get('chosen_option', e.get('chosen', '?'))}")
            print(f"  原因: {(e.get('reasoning', '') or '')[:200]}")
            print()
        print(f"--- {len(entries)} entries ---")
        return

    if args.export:
        from tain_agent.evolution.exporter import ExportPipeline
        from tain_agent.evolution.quality_gate import ExportQualityGate, render_report

        name = agent_name
        if args.skip_gate:
            print("Skipping quality gate (development mode)")
            pipeline = ExportPipeline()
            result = pipeline.export(name, output_dir=args.output, skip_gate=True)
            print(f"Exported: {result.output_path}")
            print(f"Tools: {result.tool_count} | Knowledge: {result.knowledge_count}")
            print(f"Size: {result.total_size_bytes:,} bytes")
            return

        gate = ExportQualityGate(agent_name=name)
        report = gate.evaluate()
        print(render_report(report))
        if not report.passed:
            print("\nExport rejected — quality gate not passed.")
            sys.exit(1)
        pipeline = ExportPipeline()
        result = pipeline.export(name, output_dir=args.output, gate_instance=gate)
        print(f"\nExported: {result.output_path}")
        print(f"Tools: {result.tool_count} | Knowledge: {result.knowledge_count}")
        return

    if args.eval:
        from tain_agent.evolution.quality_gate import ExportQualityGate, render_report
        gate = ExportQualityGate(agent_name=agent_name)
        report = gate.evaluate()
        print(render_report(report))
        return

    if args.import_path:
        from tain_agent.evolution.importer import ImportPipeline
        importer = ImportPipeline()
        result = importer.import_agent(args.import_path)
        print(f"Imported: {result.name} v{result.version}")
        print(f"Workspace: {result.workspace_dir}")
        if result.warnings:
            for w in result.warnings:
                print(f"  {w}")
        return

    # ── List production-ready agents ──────────────────────────────
    if args.list_production_ready:
        from tain_agent.evolution.quality_gate import ExportQualityGate
        agents = factory.list_agents()
        ready = []
        for name in agents:
            gate = ExportQualityGate(agent_name=name)
            report = gate.evaluate()
            if report.passed:
                ready.append((name, report))
        if not ready:
            print("(no production-ready agents found)")
        else:
            print()
            print(f"{'NAME':<16} {'STABLE STREAK':<14} {'SCORE':<8}")
            print("-" * 40)
            for name, report in ready:
                streak = report.stable_streak if hasattr(report, 'stable_streak') else 0
                score = report.total_score if hasattr(report, 'total_score') else 0.0
                print(f"{name:<16} {streak:<14} {score:<8.1f}")
            print()
        return

    # ── MCP serve ──────────────────────────────────────────────────
    if args.mcp_serve:
        from tain_agent.mcp.server import AgentMCPServer
        server = AgentMCPServer(agent_name)
        server.serve(mode="stdio")
        return

    # ── Export Skill Bundle ─────────────────────────────────────────
    if args.export_bundle:
        from tain_agent.evolution.skill_exporter import export_agent_bundle
        result = export_agent_bundle(agent_name, output_dir=args.output)
        status = "Exported" if result.get("success") else "Partially exported"
        print(f"{status}: {result['bundle_path']}")
        print(f"Files created: {result['files_created']}")
        if result.get("partial"):
            print("Warning: Some files could not be included (partial export).")
        return

    # ── Run agent ───────────────────────────────────────────────────
    try:
        if args.dialogue:
            from tain_agent.core.dialogue import DialogueBridge
            dialogue = DialogueBridge(agent, kernel=kernel)
            dialogue.run()
        else:
            exit_code = agent.run()
            if exit_code:
                sys.exit(exit_code)
    except KeyboardInterrupt:
        print("\n\nInterrupt received.")
        agent.stop()
        agent.print_state()
        print(f"\nAgent stopped. Use --agent {agent_name} --state to view status.")


if __name__ == "__main__":
    main()
