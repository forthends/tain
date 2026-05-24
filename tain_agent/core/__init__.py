"""Core module — Tao Agent's central nervous system.

Architecture (v0.3 — PRAL cognitive loop + multimodal):
  agent.py           — Core orchestration (protected bootstrap)
  bootstrap.py       — Tool registration closures
  conversation.py    — History management + checkpoint
  cognitive_loop.py  — PRAL: Perceive→Reason→Act→Learn
  pral_bridge.py     — CognitiveBridge: wraps agent.run() with full PRAL
  llm.py             — LLM backend abstraction
  memory.py          — Long-term memory store
  environment.py     — Environment scanner
"""
