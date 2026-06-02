# Runtime Kernel

## Purpose

The `tain_agent/runtime/` directory contains a lightweight, self-contained
runtime kernel for running exported agents independently of the full framework.

## Current Status

**Experimental (v0.5.1).** The runtime kernel is present but not yet fully
integrated with the export pipeline. It is intended as the target for
`skill_exporter` and `exporter` output.

## Components

- `identity.py` — Agent identity loading (name, role, evolution mode)
- `llm.py` — Minimal LLM client wrapper
- `__init__.py` — Runtime bootstrap

## Known Limitations

- No tool forge support (sandbox requires full framework)
- No drive system (runtime is stateless between runs)
- No evolution or self-modification capabilities
- No Web UI or ACP integration

## Relationship to Main Framework

The runtime kernel is the "export target" — a minimal dependency set that
can run a trained/evolved agent without the full framework's introspection
and self-modification infrastructure. Think of it as the "production runtime"
vs. the "development framework".
