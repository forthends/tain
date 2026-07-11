"""Core module — Tain Agent's central nervous system.

Architecture (PRAL cognitive loop + mixin decomposition):
  agent.py            — Core orchestration: __init__, run(), lifecycle
  agent_config.py     — Configuration loading, identity, phase persistence
  agent_subsystems.py — Subsystem initialization, code generation wiring
  agent_cognition.py  — PRAL cognitive enrichment (diversity, domains, rate limits)
  agent_phase.py      — Phase management, initial messages, action categories
  agent_tools.py      — Tool execution and decision logging
  bootstrap.py        — Tool registration closures
  conversation.py     — History management + checkpoint
  # cognitive_loop.py — REMOVED (dead code; evolution now wired via runtime/pral.py)
  llm.py              — LLM backend abstraction
  memory.py           — Long-term memory store
  environment.py      — Environment scanner
"""
