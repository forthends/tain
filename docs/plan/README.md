# Tain Agent Framework — Implementation Plans

Derived from [docs/design/v0-4-2-design.md](../design/v0-4-2-design.md), which analyzed Mini-Agent's design against Tain's current state.

## Plan Index

| Priority | Plan | Version | Status |
|----------|------|---------|--------|
| P0 | [LLM Retry Mechanism](p0-llm-retry.md) | v0.4.3 | pending |
| P1 | [Token-Aware Context Management](p1-token-context.md) | v0.4.3 | pending |
| P2 | [Structured LLM Logging](p2-llm-logging.md) | v0.4.4 | pending |
| P3 | [Web Chat Cancellation](p3-chat-cancel.md) | v0.4.4 | pending |
| P4 | [Agent Memory Tools](p4-memory-tools.md) | v0.4.5 | pending |
| P5 | [Tool Base Class](p5-tool-base.md) | v0.4.5 | pending |
| P6 | [Forge SKILL.md Output](p6-skill-format.md) | v0.4.5 | pending |
| P7 | [Forge Tool Templates](p7-forge-templates.md) | v0.4.5 | pending |
| P8 | [MCP Integration](p8-mcp-integration.md) | v0.5.0 | pending |
| P9 | [Background Process Management](p9-bg-process.md) | v0.5.0 | pending |
| P10 | [ACP Protocol Support](p10-acp-protocol.md) | v0.5.0 | pending |
| P11 | [Multi-Level Config Search](p11-config-search.md) | v0.5.0 | pending |
| P12 | [Smart File Truncation](p12-smart-truncation.md) | v0.5.0 | pending |

## Phase Summary

- **v0.4.3** (P0-P1): Stability — retry resilience and token-aware context
- **v0.4.4** (P2-P3): Observability — LLM call logging and chat cancellation
- **v0.4.5** (P4-P7): Agent capability — memory tools, tool contracts, forge standardization
- **v0.5.0** (P8-P12): Boundary expansion — MCP, ACP, background tasks, config, truncation
