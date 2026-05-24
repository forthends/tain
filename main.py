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
import os
import re
import subprocess
import sys
from pathlib import Path

# Ensure the project root is in sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent))

from tain_agent.core.agent import TaoAgent
from tain_agent.core.agent_factory import AgentFactory
from tain_agent.core.pral_bridge import CognitiveBridge

# ─── Constants ──────────────────────────────────────────────────────────

AGENT_NAME_HELP = (
    "Agent name (lowercase letters, digits, hyphens, underscores; "
    "1-32 chars, must start with a letter). Example: poet, alpha01"
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
        if not re.match(r"^[a-z][a-z0-9_-]{0,31}$", name):
            print("  Invalid name. Must be 1-32 chars, lowercase letters/digits/hyphens/underscores, start with a letter.")
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
    parser.add_argument("--agent", "-a", type=str, default=None,
                        help=f"Agent name to start (creates if new). {AGENT_NAME_HELP}")
    parser.add_argument("--list-agents", action="store_true",
                        help="List all agents")
    parser.add_argument("--create-agent", action="store_true",
                        help="Interactive agent creation wizard")

    # Configuration
    parser.add_argument("--config", default="config.yaml", help="Path to config file")

    # Mode
    parser.add_argument("--no-pral", action="store_true",
                        help="Disable PRAL cognitive cycle (use legacy agent.run())")
    parser.add_argument("--pral", action="store_true",
                        help="(Default) Run with full PRAL cognitive cycle")
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

    args = parser.parse_args()

    # ── Factory (for listing, creation) ─────────────────────────────
    factory = AgentFactory()

    # ── List agents ─────────────────────────────────────────────────
    if args.list_agents:
        list_agents(factory)
        return

    # ── Create agent wizard ─────────────────────────────────────────
    if args.create_agent:
        run_creation_wizard(factory, suggested_name=args.agent or "")
        return

    # ── Determine agent name ────────────────────────────────────────
    agent_name = args.agent

    # ── Daemon commands ─────────────────────────────────────────────
    if args.daemon:
        supervisor_script = Path(__file__).resolve().parent / "supervise_agent.py"
        supervisor_args = [sys.executable, str(supervisor_script)]

        try:
            if args.daemon == "stop":
                subprocess.run(supervisor_args + ["--stop"])
            elif args.daemon == "status":
                subprocess.run(supervisor_args + ["--status"])
            else:
                passthrough = []
                if agent_name:
                    passthrough.extend(["--agent", agent_name])
                if args.dialogue:
                    passthrough.append("--dialogue")
                if args.no_pral:
                    passthrough.append("--no-pral")
                if args.cycles:
                    passthrough.extend(["--cycles", str(args.cycles)])
                subprocess.run(
                    supervisor_args + ["--daemon", "--"] + passthrough
                )
        except KeyboardInterrupt:
            print()
        return

    # ── No agent specified: default or create ───────────────────────
    if not agent_name:
        # Check if config has a default_agent
        import yaml
        config_path = args.config
        cfg = {}
        if Path(config_path).exists():
            with open(config_path, "r", encoding="utf-8") as f:
                cfg = yaml.safe_load(f) or {}
        agent_name = cfg.get("agent", {}).get("default_agent", "default")

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
    agent = TaoAgent(config_path=args.config, agent_name=agent_name)

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
            print(f"[{e['id']}] {e['timestamp']}")
            print(f"  阶段: {e['phase']} | 类型: {e['decision_type']}")
            print(f"  选择: {e['chosen_option']}")
            print(f"  原因: {e['reasoning'][:200]}")
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

    # ── Run agent ───────────────────────────────────────────────────
    try:
        use_pral = not args.no_pral

        if args.dialogue:
            if use_pral:
                CognitiveBridge(agent)
            from tain_agent.core.dialogue import DialogueBridge
            dialogue = DialogueBridge(agent)
            dialogue.run()

        elif use_pral:
            print("PRAL cognitive cycle mode (Perceive -> Reason -> Act -> Learn)")
            bridge = CognitiveBridge(agent)
            bridge.run()
            if bridge._rate_limit_exit_code:
                sys.exit(bridge._rate_limit_exit_code)
        else:
            print("Legacy mode (no PRAL cognitive cycle)")
            agent.run()
    except KeyboardInterrupt:
        print("\n\nInterrupt received.")
        agent.stop()
        agent.print_state()
        print(f"\nAgent stopped. Use --agent {agent_name} --state to view status.")


if __name__ == "__main__":
    main()
